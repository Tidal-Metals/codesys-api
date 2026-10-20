PROGRAM ClockSync
// Keeps the PLC's real-time clock on UTC from an NTP server (SNTP Service SL). Every SyncPeriod it asks the
// server for UTC and measures the difference to the PLC's clock. With IsClockSetEnabled it sets the clock
// when the difference exceeds SetThresholdMs; otherwise readers correct by OffsetMs. On 2026-10-20 the
// bench PLC's clock was 4 h 1 min 24 s behind UTC (local time plus drift).
VAR
	// Settings, writable online
	Server : STRING(255) := '192.168.50.240';
	ServerPort : UINT := 123;
	OwnPort : UINT := 50123;            // the library has no defaults for the ports: 0 fails with INIT_ERROR
	SyncPeriod : TIME := T#60S;
	MaxAgeMs : ULINT := 180000;         // no good answer for this long: IsSynced goes FALSE
	IsClockSetEnabled : BOOL;           // set the PLC's clock, not just measure it
	SetThresholdMs : LINT := 50;

	// Results, readable online
	IsSynced : BOOL;                    // the last good answer is younger than MaxAgeMs
	HasOffset : BOOL;
	MeasuredOffsetMs : LINT;            // UTC minus the PLC's clock, at the last answer
	OffsetMs : LINT;                    // what readers add to the clock: 0 once the clock was set
	DriftMs : LINT;                     // MeasuredOffsetMs change since the answer before
	SyncCount : UDINT;
	ErrorCount : UDINT;
	LastError : SNTP.ERROR;
	SetCount : UDINT;
	LastSetResult : UDINT;              // runtime error code; 0 = OK
	LastSetStepMs : LINT;               // how far the last set moved the clock

	Client : SNTP.SNTPGetUTCTime;
	Timer : TON;
	IsRequesting : BOOL;
	RtcMs : ULINT;
	LastSyncRtcMs : ULINT;
	PreviousOffsetMs : LINT;
	NewTimeMs : ULINT;
END_VAR
// ---- implementation ----
SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := RtcMs);
Timer(IN := NOT Timer.Q, PT := SyncPeriod);
IF NOT IsRequesting AND (Timer.Q OR SyncCount + ErrorCount = 0) THEN
	IsRequesting := TRUE;
END_IF

// The request starts on a rising edge of xExecute; IsRequesting is FALSE for at least one call in between.
Client(xExecute := IsRequesting, sSNTPServer := Server, uiSNTPPort := ServerPort, uiOwnPort := OwnPort);
IF Client.xDone THEN
	PreviousOffsetMs := MeasuredOffsetMs;
	// uliTimestamp: server UTC corrected for the round trip; uliReceiveClientTS: the PLC's clock at that moment
	MeasuredOffsetMs := ULINT_TO_LINT(Client.uliTimestamp) - ULINT_TO_LINT(Client.uliReceiveClientTS);
	IF HasOffset THEN
		DriftMs := MeasuredOffsetMs - PreviousOffsetMs;
	END_IF
	HasOffset := TRUE;
	OffsetMs := MeasuredOffsetMs;
	LastSyncRtcMs := RtcMs;
	IF IsClockSetEnabled AND ABS(MeasuredOffsetMs) > SetThresholdMs THEN
		NewTimeMs := LINT_TO_ULINT(ULINT_TO_LINT(RtcMs) + MeasuredOffsetMs);
		LastSetResult := SysTimeRtc.SysTimeRtcHighResSet(pTimestamp := NewTimeMs);
		IF LastSetResult = 0 THEN
			SetCount := SetCount + 1;
			LastSetStepMs := MeasuredOffsetMs;
			OffsetMs := 0;
			LastSyncRtcMs := NewTimeMs;
		END_IF
	ELSIF IsClockSetEnabled AND SetCount > 0 THEN
		OffsetMs := 0;                  // within the threshold of a clock we set: use it as it is
	END_IF
	SyncCount := SyncCount + 1;
	IsRequesting := FALSE;
ELSIF Client.xError THEN
	LastError := Client.eError;
	ErrorCount := ErrorCount + 1;
	IsRequesting := FALSE;
END_IF
IsSynced := HasOffset AND RtcMs >= LastSyncRtcMs AND_THEN RtcMs - LastSyncRtcMs < MaxAgeMs;
