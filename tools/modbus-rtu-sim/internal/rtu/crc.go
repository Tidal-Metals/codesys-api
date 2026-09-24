// Package rtu frames Modbus RTU traffic observed on a shared RS485 bus.
package rtu

// CRC16 returns the Modbus RTU CRC of data (polynomial 0xA001, init 0xFFFF).
func CRC16(data []byte) uint16 {
	crc := uint16(0xFFFF)
	for _, b := range data {
		crc ^= uint16(b)
		for range 8 {
			if crc&1 != 0 {
				crc = crc>>1 ^ 0xA001
			} else {
				crc >>= 1
			}
		}
	}
	return crc
}

// AppendCRC appends the CRC of payload, low byte first, as sent on the wire.
func AppendCRC(payload []byte) []byte {
	crc := CRC16(payload)
	return append(payload, byte(crc), byte(crc>>8))
}

// hasValidCRC reports whether frame ends with the CRC of its preceding bytes.
func hasValidCRC(frame []byte) bool {
	if len(frame) < 4 {
		return false
	}
	body := frame[:len(frame)-2]
	crc := CRC16(body)
	return frame[len(frame)-2] == byte(crc) && frame[len(frame)-1] == byte(crc>>8)
}
