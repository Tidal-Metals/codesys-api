package rtu

// maxFrameLen is the Modbus RTU ADU limit; no candidate may exceed it.
const maxFrameLen = 256

// maxUnitAddress is the highest valid Modbus serial address (0 is broadcast).
const maxUnitAddress = 247

// Kind classifies a CRC-valid frame by its position in a transaction.
type Kind int

const (
	KindRequest Kind = iota
	KindResponse
	KindException
)

func (k Kind) String() string {
	switch k {
	case KindRequest:
		return "request"
	case KindResponse:
		return "response"
	case KindException:
		return "exception"
	}
	return "unknown"
}

// Frame is one CRC-valid ADU extracted from the byte stream.
type Frame struct {
	Raw      []byte
	Unit     byte
	Function byte
	Kind     Kind
	// Eligible is true only when the frame began on a known boundary (after
	// silence or directly after another valid frame) and its length was not
	// ambiguous. Only eligible requests may be answered.
	Eligible bool
	// FollowedByData is true when more bytes were already buffered after this
	// frame, meaning the master has moved on and a reply would collide.
	FollowedByData bool
}

// Stats counts framer decisions since creation.
type Stats struct {
	Frames          uint64 `json:"frames"`
	Requests        uint64 `json:"requests"`
	Responses       uint64 `json:"responses"`
	Exceptions      uint64 `json:"exceptions"`
	Ambiguous       uint64 `json:"ambiguous"`
	Unsynced        uint64 `json:"unsyncedFrames"`
	DiscardedBytes  uint64 `json:"discardedBytes"`
	PartialDiscards uint64 `json:"partialDiscards"`
}

// Framer turns arbitrary serial reads (split or coalesced) into frames. A
// USB read is not a frame: callers Feed whatever bytes arrive and call Idle
// after a line silence long enough to prove the current frame has ended.
type Framer struct {
	buf    []byte
	synced bool
	stats  Stats
}

// NewFramer returns a framer that is unsynchronised until the first silence
// or the first valid frame.
func NewFramer() *Framer {
	return &Framer{buf: make([]byte, 0, 2*maxFrameLen)}
}

func (f *Framer) Stats() Stats { return f.stats }

// Reset drops buffered bytes and synchronisation (after a port reopen) but
// keeps the cumulative statistics.
func (f *Framer) Reset() {
	f.buf = f.buf[:0]
	f.synced = false
}

// Pending reports how many bytes await more data or silence.
func (f *Framer) Pending() int { return len(f.buf) }

// Feed appends received bytes and returns every complete frame now available.
func (f *Framer) Feed(data []byte) []Frame {
	f.buf = append(f.buf, data...)
	var frames []Frame
	for len(f.buf) > 0 {
		result := parseAt(f.buf)
		if result.status == needMore {
			break
		}
		if result.status == invalid {
			f.buf = f.buf[1:]
			f.synced = false
			f.stats.DiscardedBytes++
			continue
		}
		frames = append(frames, f.accept(result))
	}
	f.compact()
	if len(frames) > 0 {
		frames[len(frames)-1].FollowedByData = len(f.buf) > 0
		for i := 0; i < len(frames)-1; i++ {
			frames[i].FollowedByData = true
		}
	}
	return frames
}

// Idle signals line silence: buffered bytes can no longer complete a frame,
// so they are discarded and the next byte starts a new frame.
func (f *Framer) Idle() {
	if len(f.buf) > 0 {
		f.stats.DiscardedBytes += uint64(len(f.buf))
		f.stats.PartialDiscards++
		f.buf = f.buf[:0]
	}
	f.synced = true
}

func (f *Framer) accept(result parseResult) Frame {
	raw := make([]byte, result.length)
	copy(raw, f.buf[:result.length])
	f.buf = f.buf[result.length:]
	frame := Frame{
		Raw:      raw,
		Unit:     raw[0],
		Function: raw[1],
		Kind:     result.kind,
		Eligible: f.synced && !result.ambiguous,
	}
	f.stats.Frames++
	switch result.kind {
	case KindRequest:
		f.stats.Requests++
	case KindResponse:
		f.stats.Responses++
	case KindException:
		f.stats.Exceptions++
	}
	if result.ambiguous {
		f.stats.Ambiguous++
	}
	if !f.synced {
		f.stats.Unsynced++
	}
	f.synced = true
	return frame
}

// compact moves unread bytes to the front so the buffer does not grow.
func (f *Framer) compact() {
	if cap(f.buf)-len(f.buf) < maxFrameLen {
		f.buf = append(make([]byte, 0, 2*maxFrameLen), f.buf...)
	}
}

type parseStatus int

const (
	matched parseStatus = iota
	needMore
	invalid
)

type parseResult struct {
	status    parseStatus
	length    int
	kind      Kind
	ambiguous bool
}

type candidate struct {
	length int // 0 means the length byte has not arrived yet
	kind   Kind
}

// parseAt decides whether buf begins with a complete CRC-valid frame.
func parseAt(buf []byte) parseResult {
	if buf[0] > maxUnitAddress {
		return parseResult{status: invalid}
	}
	if len(buf) < 2 {
		return parseResult{status: needMore}
	}
	candidates := candidatesFor(buf)
	if len(candidates) == 0 {
		return parseResult{status: invalid}
	}
	var hits []candidate
	waiting := false
	for _, c := range candidates {
		switch {
		case c.length > maxFrameLen:
			// Impossible byte count; this start cannot be a frame of this kind.
		case c.length == 0 || c.length > len(buf):
			waiting = true
		case hasValidCRC(buf[:c.length]):
			hits = append(hits, c)
		}
	}
	if len(hits) == 0 {
		if waiting {
			return parseResult{status: needMore}
		}
		return parseResult{status: invalid}
	}
	// Two different CRC-valid lengths from one start cannot be told apart.
	hit := hits[0]
	return parseResult{status: matched, length: hit.length, kind: hit.kind, ambiguous: len(hits) > 1}
}

// candidatesFor lists the possible frame lengths for the function at buf[1].
func candidatesFor(buf []byte) []candidate {
	function := buf[1]
	if function&0x80 != 0 {
		if isKnownFunction(function &^ 0x80) {
			return []candidate{{length: 5, kind: KindException}}
		}
		return nil
	}
	switch function {
	case 1, 2, 3, 4:
		return []candidate{{length: 8, kind: KindRequest}, byteCountCandidate(buf, 2, 5, KindResponse)}
	case 5, 6:
		// Write-single responses echo the request; the caller filters echoes.
		return []candidate{{length: 8, kind: KindRequest}}
	case 15, 16:
		return []candidate{byteCountCandidate(buf, 6, 9, KindRequest), {length: 8, kind: KindResponse}}
	}
	return nil
}

// byteCountCandidate sizes a frame from its byte-count field at index.
func byteCountCandidate(buf []byte, index, overhead int, kind Kind) candidate {
	if len(buf) <= index {
		return candidate{kind: kind}
	}
	length := overhead + int(buf[index])
	if length > maxFrameLen {
		return candidate{length: maxFrameLen + 1, kind: kind}
	}
	return candidate{length: length, kind: kind}
}

func isKnownFunction(function byte) bool {
	switch function {
	case 1, 2, 3, 4, 5, 6, 15, 16:
		return true
	}
	return false
}
