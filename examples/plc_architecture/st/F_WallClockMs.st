FUNCTION F_WallClockMs : ULINT
// Milliseconds since 1970 from the controller's real-time clock, to compare with senders' timestamps.
// Only meaningful while the clock is synchronized (SNTP).
VAR
	Timestamp : ULINT;
END_VAR
// ---- implementation ----
SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := Timestamp);
F_WallClockMs := Timestamp;
