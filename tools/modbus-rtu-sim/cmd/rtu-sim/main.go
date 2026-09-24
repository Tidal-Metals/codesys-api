// Command rtu-sim serves simulated Modbus RTU slaves on one RS485 adapter.
//
// Usage: rtu-sim --config <file>
//
// stdout carries JSON-line lifecycle events; stderr carries diagnostics and,
// when traceFrames is set, one line per frame. The status file is replaced
// atomically every statusIntervalMs with counters and port state.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"time"

	"codesys-api/tools/modbus-rtu-sim/internal/device"
	"codesys-api/tools/modbus-rtu-sim/internal/serialrun"
)

func main() {
	configPath := flag.String("config", "", "worker configuration JSON")
	flag.Parse()
	if *configPath == "" {
		fmt.Fprintln(os.Stderr, "rtu-sim: --config is required")
		os.Exit(2)
	}
	if err := run(*configPath); err != nil {
		fmt.Fprintln(os.Stderr, "rtu-sim:", err)
		os.Exit(1)
	}
}

func run(configPath string) error {
	cfg, err := loadConfig(configPath)
	if err != nil {
		return err
	}
	mode, err := cfg.serialMode()
	if err != nil {
		return err
	}
	units, err := cfg.units()
	if err != nil {
		return err
	}
	bank, err := device.NewBank(units)
	if err != nil {
		return err
	}

	events := newEventWriter(os.Stdout)
	status := &serialrun.Status{}
	started := time.Now()
	status.Update(func(s *serialrun.Snapshot) {
		s.Version, s.PID, s.StartedAt = configVersion, os.Getpid(), started
		s.ConfiguredCOM, s.USBSerial = cfg.Port, cfg.USBSerial
	})
	var trace io.Writer
	if cfg.TraceFrames {
		trace = os.Stderr
	}
	runner := serialrun.NewRunner(serialrun.Options{
		Port: cfg.Port, USBSerial: cfg.USBSerial, Mode: mode,
		IdleGap: cfg.idleGap(), Trace: trace, Events: events.write,
	}, bank, status)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	events.write("started", map[string]any{
		"config": configPath, "port": cfg.Port, "usbSerial": cfg.USBSerial,
		"baudrate": cfg.Baudrate, "units": bank.IDs(),
	})
	done := make(chan struct{})
	go publishStatus(ctx, done, cfg, status, bank)
	runner.Run(ctx)
	<-done
	events.write("stopped", nil)
	return nil
}

// publishStatus writes the status file on every interval and once at exit.
func publishStatus(ctx context.Context, done chan<- struct{}, cfg Config, status *serialrun.Status, bank *device.Bank) {
	defer close(done)
	if cfg.StatusFile == "" {
		<-ctx.Done()
		return
	}
	ticker := time.NewTicker(time.Duration(cfg.StatusIntervalMs) * time.Millisecond)
	defer ticker.Stop()
	for {
		status.Update(func(s *serialrun.Snapshot) { s.HeartbeatAt = time.Now(); s.Units = bank.Snapshot() })
		if err := serialrun.WriteFile(cfg.StatusFile, status.Copy()); err != nil {
			fmt.Fprintln(os.Stderr, "rtu-sim: status write:", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

type eventWriter struct {
	mu  sync.Mutex
	enc *json.Encoder
}

func newEventWriter(w io.Writer) *eventWriter {
	return &eventWriter{enc: json.NewEncoder(w)}
}

func (e *eventWriter) write(event string, fields map[string]any) {
	record := map[string]any{"time": time.Now().Format(time.RFC3339Nano), "event": event}
	for key, value := range fields {
		record[key] = value
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	_ = e.enc.Encode(record)
}
