package rtu

import "time"

// EchoFilter removes our own transmission if the adapter's receiver hears it.
// Bytes that match the expected echo are held until the match completes or
// fails, so a genuine frame that happens to share a prefix is never lost.
//
// Replies that differ from their request are evidence of whether the adapter
// echoes at all: their echo either arrives or it does not. A reply identical
// to its request (FC05/FC06 success) proves nothing, because its echo looks
// exactly like the master repeating the request.
type EchoFilter struct {
	expected []byte
	held     []byte
	deadline time.Time
	evidence bool
	echoes   uint64
	// Echoes and misses of evidence expectations since the last Reset.
	evidenceEchoes uint64
	evidenceMisses uint64
}

// Echoes counts complete echoes removed.
func (e *EchoFilter) Echoes() uint64 { return e.echoes }

// KnownAbsent reports that evidence replies went unechoed and none was echoed.
func (e *EchoFilter) KnownAbsent() bool { return e.evidenceMisses > 0 && e.evidenceEchoes == 0 }

// Expect arms the filter for tx until now+window. evidence marks a tx that
// differs from the request it answers.
func (e *EchoFilter) Expect(tx []byte, now time.Time, window time.Duration, evidence bool) {
	e.expected = append(e.expected[:0], tx...)
	e.held = e.held[:0]
	e.deadline = now.Add(window)
	e.evidence = evidence
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
			e.miss()
			return append(out, data[i:]...)
		}
		e.held = append(e.held, b)
		if len(e.held) == len(e.expected) {
			e.echoes++
			if e.evidence {
				e.evidenceEchoes++
			}
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
	e.miss()
	return out
}

// Reset forgets any expected echo and the echo evidence (after a port
// reopen the adapter may be a different one); the echo count is kept.
func (e *EchoFilter) Reset() {
	e.disarm()
	e.evidenceEchoes, e.evidenceMisses = 0, 0
}

func (e *EchoFilter) miss() {
	if e.evidence {
		e.evidenceMisses++
	}
	e.disarm()
}

func (e *EchoFilter) disarm() {
	e.expected = e.expected[:0]
	e.held = e.held[:0]
	e.evidence = false
}
