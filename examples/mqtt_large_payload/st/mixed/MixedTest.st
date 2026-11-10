PROGRAM MixedTest
// Mixed-rate load, full values (no report by exception): ScaleTest's 2,000 tags as two streams.
// Slow: the 1,000 BOOL and 500 DINT (75 %) once a second; Fast: the 500 REAL (25 %, analog) ten times a second.
// mixed_rate_test.py drives it: TagsPerMessage sets consolidated (one message per stream) or grouped messages,
// QoSLevel 0 or 1. Scan figures are PLC_PRG's of the scan before (they are computed at its end).
VAR
	// Settings, written online
	IsEnabled : BOOL;
	QoSLevel : BYTE;
	SlowTagsPerMessage : UINT := 1500;
	FastTagsPerMessage : UINT := 500;
	SlowPublishers : UINT := 1;
	FastPublishers : UINT := 1;
	SlowPeriod : TIME := T#1S;
	FastPeriod : TIME := T#100MS;
	ToleranceUs : ULINT := 20000;
	ResetStats : BOOL;

	Slow : FB_MixedStream;
	Fast : FB_MixedStream;
	IsSendInFlight : BOOL;                  // PLC_PRG.CallClient keeps calling the client while this is TRUE

	// Results, read online
	ScanCount : UDINT;                      // scans while enabled
	SumCycleUs : ULINT;
	MaxCycleUs : UDINT;
	SumScanClientUs : ULINT;
	MaxScanClientUs : UDINT;
	MaxIntervalUs : UDINT;
	MinIntervalUs : UDINT := 16#FFFFFFFF;
	SumClientCalls : ULINT;
	IsCounting : BOOL;
END_VAR
// ---- implementation ----
IF ResetStats THEN
	ScanCount := 0; SumCycleUs := 0; MaxCycleUs := 0; SumScanClientUs := 0; MaxScanClientUs := 0;
	MaxIntervalUs := 0; MinIntervalUs := 16#FFFFFFFF; SumClientCalls := 0;
END_IF
IF IsCounting THEN
	ScanCount := ScanCount + 1;
	SumCycleUs := SumCycleUs + PLC_PRG.CycleUs;
	MaxCycleUs := MAX(MaxCycleUs, PLC_PRG.CycleUs);
	SumScanClientUs := SumScanClientUs + PLC_PRG.ScanClientUs;
	MaxScanClientUs := MAX(MaxScanClientUs, PLC_PRG.ScanClientUs);
	MaxIntervalUs := MAX(MaxIntervalUs, PLC_PRG.IntervalUs);
	MinIntervalUs := MIN(MinIntervalUs, PLC_PRG.IntervalUs);
	SumClientCalls := SumClientCalls + INT_TO_ULINT(PLC_PRG.ClientCall);
END_IF
IsCounting := IsEnabled;

Slow(IsEnabled := IsEnabled, StreamId := 'S', FirstTag := 1, LastTag := 1500, TagsPerMessage := SlowTagsPerMessage,
	Publishers := SlowPublishers, Period := SlowPeriod, QoSLevel := QoSLevel, Topic := 'raw_data_demo/mixed/slow',
	ToleranceUs := ToleranceUs, ResetStats := ResetStats);
Fast(IsEnabled := IsEnabled, StreamId := 'F', FirstTag := 1501, LastTag := 2000, TagsPerMessage := FastTagsPerMessage,
	Publishers := FastPublishers, Period := FastPeriod, QoSLevel := QoSLevel, Topic := 'raw_data_demo/mixed/fast',
	ToleranceUs := ToleranceUs, ResetStats := ResetStats);
ResetStats := FALSE;
IsSendInFlight := Slow.IsRoundActive OR Fast.IsRoundActive;
