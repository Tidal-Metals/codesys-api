// Package serialrun owns one serial port and runs its ordered bus loop.
package serialrun

import (
	"context"
	"encoding/hex"
	"fmt"
	"io"
	"strings"
	"time"

	"go.bug.st/serial"
	"go.bug.st/serial/enumerator"

	"codesys-api/tools/modbus-rtu-sim/internal/device"
	"codesys-api/tools/modbus-rtu-sim/internal/rtu"
)

const (
	readPoll         = 5 * time.Millisecond
	minBackoff       = 250 * time.Millisecond
	maxBackoff       = 5 * time.Second
	presenceInterval = 2 * time.Second
	echoMargin       = 100 * time.Millisecond
)

// Options configures one bus worker.
type Options struct {
	// Port is the configured COM name; USBSerial, when set, wins so the
	// adapter is found even if Windows renumbers it after a replug.
	Port      string
	USBSerial string
	Mode      serial.Mode
	// IdleGap is the silence that proves a frame has ended. It must exceed
	// the adapter's USB latency timer, not just 3.5 character times.
	IdleGap time.Duration
	Trace   io.Writer
	Events  func(event string, fields map[string]any)
}

// Runner serves one bank on one serial port and reopens it on failure.
type Runner struct {
	opts   Options
	bank   *device.Bank
	status *Status
	framer *rtu.Framer
	echo   rtu.EchoFilter
	port   serial.Port
}

func NewRunner(opts Options, bank *device.Bank, status *Status) *Runner {
	if opts.Events == nil {
		opts.Events = func(string, map[string]any) {}
	}
	return &Runner{opts: opts, bank: bank, status: status, framer: rtu.NewFramer()}
}

// Run blocks until ctx is cancelled, reopening the port with bounded backoff.
func (r *Runner) Run(ctx context.Context) {
	backoff := minBackoff
	for ctx.Err() == nil {
		name, err := r.resolvePort()
		var port serial.Port
		if err == nil {
			port, err = serial.Open(name, &r.opts.Mode)
		}
		if err != nil {
			r.recordError(fmt.Errorf("open %s: %w", r.describeTarget(name), err))
			sleep(ctx, backoff)
			backoff = min(2*backoff, maxBackoff)
			continue
		}
		backoff = minBackoff
		r.recordOpen(name)
		err = r.serve(ctx, port, name)
		port.Close()
		r.recordClosed(name, err)
		if err != nil {
			sleep(ctx, minBackoff)
		}
	}
}

// serve runs the read/reply loop until the port fails or ctx ends.
func (r *Runner) serve(ctx context.Context, port serial.Port, name string) error {
	if err := port.SetReadTimeout(readPoll); err != nil {
		return fmt.Errorf("set read timeout: %w", err)
	}
	r.port = port
	r.framer.Reset()
	r.echo.Reset()
	buf := make([]byte, 512)
	lastRx := time.Now()
	lastPresence := lastRx
	idleSignalled := false
	for ctx.Err() == nil {
		n, err := port.Read(buf)
		now := time.Now()
		if err != nil {
			return fmt.Errorf("read: %w", err)
		}
		if n > 0 {
			lastRx, idleSignalled = now, false
			r.status.Update(func(s *Snapshot) { s.RxBytes += uint64(n); s.LastRxAt = now })
			if err := r.process(r.echo.Filter(buf[:n], now), now); err != nil {
				return err
			}
			continue
		}
		if held := r.echo.Expire(now); len(held) > 0 {
			if err := r.process(held, now); err != nil {
				return err
			}
		}
		if !idleSignalled && now.Sub(lastRx) >= r.opts.IdleGap {
			r.framer.Idle()
			r.syncFramerStats()
			idleSignalled = true
		}
		// A quiet line is normal; only a vanished device ends the session.
		if now.Sub(lastRx) >= presenceInterval && now.Sub(lastPresence) >= presenceInterval {
			lastPresence = now
			if !portPresent(name) {
				return fmt.Errorf("%s disappeared from the system", name)
			}
		}
	}
	return nil
}

// process frames received bytes and answers eligible requests for our units.
func (r *Runner) process(data []byte, rxAt time.Time) error {
	if len(data) == 0 {
		return nil
	}
	for _, frame := range r.framer.Feed(data) {
		action := r.decide(frame)
		if action == "reply" {
			if err := r.reply(frame, rxAt); err != nil {
				return err
			}
		}
		r.trace("RX", frame.Raw, fmt.Sprintf("%s unit=%d fc=%d eligible=%t action=%s",
			frame.Kind, frame.Unit, frame.Function, frame.Eligible, action))
	}
	r.syncFramerStats()
	return nil
}

// decide returns reply, or the reason a frame is not answered.
func (r *Runner) decide(frame rtu.Frame) string {
	if frame.Kind != rtu.KindRequest || !r.bank.Owns(frame.Unit) {
		return "ignore"
	}
	if !frame.Eligible {
		r.bank.Skip(frame.Unit)
		r.status.Update(func(s *Snapshot) { s.Ineligible++ })
		return "skip-unsynced"
	}
	if frame.FollowedByData {
		r.bank.Skip(frame.Unit)
		r.status.Update(func(s *Snapshot) { s.Stale++ })
		return "skip-stale"
	}
	return "reply"
}

func (r *Runner) reply(frame rtu.Frame, rxAt time.Time) error {
	reply, outcome := r.bank.Handle(frame.Raw)
	if reply == nil {
		return nil
	}
	if _, err := r.port.Write(reply); err != nil {
		r.status.Update(func(s *Snapshot) { s.WriteErrors++ })
		return fmt.Errorf("write reply to unit %d: %w", frame.Unit, err)
	}
	now := time.Now()
	r.echo.Expect(reply, now, r.wireTime(len(reply))+echoMargin)
	latency := now.Sub(rxAt).Microseconds()
	r.status.Update(func(s *Snapshot) {
		s.TxBytes += uint64(len(reply))
		s.LastTxAt = now
		s.LastReplyLatencyUs = latency
		s.MaxReplyLatencyUs = max(s.MaxReplyLatencyUs, latency)
	})
	direction := "TX"
	if outcome == device.Excepted {
		direction = "TX-exception"
	}
	r.trace(direction, reply, fmt.Sprintf("unit=%d latencyUs=%d", frame.Unit, latency))
	return nil
}

// wireTime is how long bytes take on the line at the configured framing.
func (r *Runner) wireTime(bytes int) time.Duration {
	bits := 1 + r.opts.Mode.DataBits + 1
	if r.opts.Mode.Parity != serial.NoParity {
		bits++
	}
	if r.opts.Mode.StopBits == serial.TwoStopBits {
		bits++
	}
	return time.Duration(bytes*bits) * time.Second / time.Duration(r.opts.Mode.BaudRate)
}

func (r *Runner) syncFramerStats() {
	stats, echoes := r.framer.Stats(), r.echo.Echoes()
	r.status.Update(func(s *Snapshot) { s.Framer, s.Echoes = stats, echoes })
}

func (r *Runner) trace(direction string, raw []byte, detail string) {
	if r.opts.Trace == nil {
		return
	}
	fmt.Fprintf(r.opts.Trace, "%s %s %s %s\n", time.Now().Format("15:04:05.000000"), direction,
		hex.EncodeToString(raw), detail)
}

// resolvePort finds the adapter by USB serial when configured, else by name.
func (r *Runner) resolvePort() (string, error) {
	if r.opts.USBSerial == "" {
		return r.opts.Port, nil
	}
	ports, err := enumerator.GetDetailedPortsList()
	if err != nil {
		return "", fmt.Errorf("enumerate ports: %w", err)
	}
	for _, port := range ports {
		if port.IsUSB && serialMatches(port.SerialNumber, r.opts.USBSerial) {
			return port.Name, nil
		}
	}
	return "", fmt.Errorf("USB adapter %s is not present", r.opts.USBSerial)
}

// serialMatches accepts FTDI's per-interface suffix (BG00XX03 -> BG00XX03A).
func serialMatches(reported, want string) bool {
	reported, want = strings.ToUpper(reported), strings.ToUpper(want)
	return reported == want || (len(reported) == len(want)+1 && strings.HasPrefix(reported, want))
}

func (r *Runner) describeTarget(name string) string {
	switch {
	case r.opts.USBSerial == "":
		return name
	case name == "":
		return "USB " + r.opts.USBSerial
	}
	return fmt.Sprintf("%s (USB %s)", name, r.opts.USBSerial)
}

func (r *Runner) recordOpen(name string) {
	now := time.Now()
	r.status.Update(func(s *Snapshot) {
		if s.OpenCount > 0 {
			s.ReopenCount++
		}
		s.OpenCount++
		s.PortOpen, s.ActivePort, s.OpenedAt = true, name, now
	})
	fields := map[string]any{"port": name}
	if name != r.opts.Port {
		fields["configuredPort"] = r.opts.Port
	}
	r.opts.Events("port_open", fields)
}

func (r *Runner) recordClosed(name string, err error) {
	r.status.Update(func(s *Snapshot) { s.PortOpen = false })
	if err != nil {
		r.recordError(err)
	}
	r.opts.Events("port_closed", map[string]any{"port": name, "error": errorText(err)})
}

func (r *Runner) recordError(err error) {
	now := time.Now()
	text := err.Error()
	var previous string
	r.status.Update(func(s *Snapshot) {
		previous = s.LastError
		s.LastError, s.LastErrorAt = text, now
	})
	// Repeated identical open failures during backoff would flood the log.
	if text != previous {
		r.opts.Events("error", map[string]any{"error": text})
	}
}

func portPresent(name string) bool {
	ports, err := serial.GetPortsList()
	if err != nil {
		return true // cannot tell; let a real I/O error decide
	}
	for _, port := range ports {
		if strings.EqualFold(port, name) {
			return true
		}
	}
	return false
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func sleep(ctx context.Context, d time.Duration) {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}
