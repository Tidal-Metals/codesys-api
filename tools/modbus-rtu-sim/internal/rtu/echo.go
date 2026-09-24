package rtu

import "time"

// EchoFilter removes our own transmission if the adapter's receiver hears it.
// Bytes that match the expected echo are held until the match completes or
// fails, so a genuine frame that happens to share a prefix is never lost.
type EchoFilter struct {
	expected []byte
	held     []byte
	deadline time.Time
	echoes   uint64
}

// Echoes counts complete echoes removed.
func (e *EchoFilter) Echoes() uint64 { return e.echoes }

// Expect arms the filter for tx until now+window.
func (e *EchoFilter) Expect(tx []byte, now time.Time, window time.Duration) {
	e.expected = append(e.expected[:0], tx...)
	e.held = e.held[:0]
	e.deadline = now.Add(window)
}

// Filter returns the bytes that are not part of an expected echo.
func (e *EchoFilter) Filter(data []byte, now time.Time) []byte {
	out := e.Expire(now)
	for i, b := range data {
		if len(e.expected) == 0 {
			return append(out, data[i:]...)
		}
		if b != e.expected[len(e.held)] {
			out = append(out, e.held...)
			e.disarm()
			return append(out, data[i:]...)
		}
		e.held = append(e.held, b)
		if len(e.held) == len(e.expected) {
			e.echoes++
			e.disarm()
		}
	}
	return out
}

// Expire releases held bytes once the echo window has passed.
func (e *EchoFilter) Expire(now time.Time) []byte {
	if len(e.expected) == 0 || now.Before(e.deadline) {
		return nil
	}
	out := append([]byte(nil), e.held...)
	e.disarm()
	return out
}

// Reset forgets any expected echo (after a port reopen); the count is kept.
func (e *EchoFilter) Reset() { e.disarm() }

func (e *EchoFilter) disarm() {
	e.expected = e.expected[:0]
	e.held = e.held[:0]
}
