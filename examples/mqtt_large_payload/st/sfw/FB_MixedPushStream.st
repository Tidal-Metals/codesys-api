FUNCTION_BLOCK FB_MixedPushStream
// One periodic stream of the mixed-rate test through MQTT.MqttStoreForward (MixedPushTest, mixed_rate_test.py --push).
// FB_MixedStream's messages, built the same way (same tags, values, "MIX:<StreamId>:<round>:<part>:<parts>:<UTC ms>"
// header and "<tag>:<value>" lines, all parts back to back in Data), but each part is handed to the shared block Sfw
// with Push (a copy, so Data is rebuilt next round while earlier rounds are still held) instead of MQTTPublish blocks.
// QoS 1 only. The statistics keep FB_MixedStream's names and units, with these differences:
// - a period is never skipped because the previous round is still in flight: the block buffers it. Skipped counts
//   only periods a late scan jumped over; SkippedOffline the periods due while the broker was down (unless IsPushOffline);
// - TimeoutCount counts parts Push refused (not configured, AcceptPush FALSE, too large for a slot); drops and broker
//   refusals are the shared block's (MixedPushTest.DroppedCount, RefusedCount), not attributable to a stream;
// - a round is done when the block no longer holds anything pushed before or with it (ServiceRounds); send times run
//   from the build's end to that scan, so SendScans is at least 1; PartsDone counts the parts pushed in done rounds.
// Up to MAX_TRACKED rounds are timed at once; beyond that the oldest is forgotten (UntrackedCount, not in RoundsDone).
VAR CONSTANT
	MAX_BYTES : UDINT := 32000;
	MAX_PARTS : UINT := 64;
	MAX_TRACKED : UINT := 128;
	BOOL_COUNT : UINT := 1000;
	INT_COUNT : UINT := 500;
	REAL_COUNT : UINT := 500;
	MIN_PERIOD_US : ULINT := 10000;
END_VAR
VAR_INPUT
	IsEnabled : BOOL;
	StreamId : STRING(1);
	FirstTag : UINT;                        // 1 .. 2000, ScaleTest numbering: BOOL 1-1000, DINT 1001-1500, REAL 1501-2000
	LastTag : UINT;
	TagsPerMessage : UINT;
	Period : TIME;
	Topic : STRING(64);
	ToleranceUs : ULINT;                    // a period is due this much early (task jitter)
	IsPushOffline : BOOL;                   // push while the broker is down (the block holds it); FALSE skips, as FB_MixedStream
	BlockNowMs : UDINT;                     // SysTimeGetMs() taken just before the block's last call (MixedPushTest)
	ResetStats : BOOL;
END_VAR
VAR_IN_OUT
	Sfw : MQTT.MqttStoreForward;            // shared by both streams, owned and called by MixedPushTest
END_VAR
VAR_OUTPUT
	IsRoundActive : BOOL;                   // a pushed round still has a part in the block
END_VAR
VAR
	// Results, read online (microseconds unless named *Scans/*Count)
	Round : UDINT;                          // rounds started since download (not reset; the broker check uses it)
	RoundsStarted : UDINT;
	RoundsDone : UDINT;
	Skipped : UDINT;                        // periods a late scan jumped over (never for a round in flight)
	SkippedOffline : UDINT;                 // periods lost because the broker was not connected (IsPushOffline FALSE)
	PartsDone : UDINT;                      // parts pushed in the rounds that are done
	TimeoutCount : UDINT;                   // parts Push refused
	OverflowCount : UDINT;                  // rounds that did not fit MAX_BYTES / MAX_PARTS (not sent)
	LastBytes : UDINT;                      // all parts of the last round, headers included
	LastParts : UINT;
	LastBuildUs : UDINT;                    // value update + formatting of the whole round, in its first scan
	MaxBuildUs : UDINT;
	SumBuildUs : ULINT;
	LastSendUs : UDINT;                     // build finished -> the block holds nothing of the round (PUBACKs)
	MaxSendUs : UDINT;
	SumSendUs : ULINT;
	LastSendScans : UDINT;                  // scans from the build to that scan (at least 1)
	MaxSendScans : UDINT;
	SumSendScans : ULINT;
	MaxLateUs : UDINT;                      // how late after its due time a round started (scan phase)
	LastPushUs : UDINT;                     // the round's Push calls (copies into the block's storage)
	MaxPushUs : UDINT;
	SumPushUs : ULINT;
	MaxRoundsActive : UINT;                 // most rounds held at once
	UntrackedCount : UDINT;                 // rounds whose completion was not timed (more than MAX_TRACKED held)

	// State
	PartStart : ARRAY[0..MAX_PARTS - 1] OF UDINT;
	PartLength : ARRAY[0..MAX_PARTS - 1] OF UDINT;
	Data : ARRAY[0..MAX_BYTES - 1] OF BYTE;
	Bools : ARRAY[1..BOOL_COUNT] OF BOOL;
	Ints : ARRAY[1..INT_COUNT] OF DINT;
	Reals : ARRAY[1..REAL_COUNT] OF REAL;
	// rounds pushed and not yet done, oldest at TrackHead (a ring)
	TrackRequestUs : ARRAY[0..MAX_TRACKED - 1] OF ULINT;
	TrackPushMs : ARRAY[0..MAX_TRACKED - 1] OF UDINT;	// SysTimeGetMs() after the round's last Push
	TrackScan : ARRAY[0..MAX_TRACKED - 1] OF UDINT;
	TrackParts : ARRAY[0..MAX_TRACKED - 1] OF UINT;
	TrackHead : UINT;
	TrackCount : UINT;
	IsScheduled : BOOL;
	IsDue : BOOL;
	IsBuildOk : BOOL;
	NowTimeUs : ULINT;
	PeriodUs : ULINT;
	NextDueUs : ULINT;
	DueUs : ULINT;
	StepStartUs : ULINT;
	RequestUs : ULINT;
	ServiceNowUs : ULINT;
	ScanCount : UDINT;
	RoundParts : UINT;
	RoundPushed : UINT;
	Used : UDINT;
	Part : UINT;
	PartFirst : UINT;
	PartLast : UINT;
	Tag : UINT;
	Index : UINT;
	Kind : UDINT;
	StampMs : ULINT;
	StampText : STRING(24);
	Header : STRING(80);
	ValueText : STRING(40);
	RealValue : REAL;
END_VAR
// ---- implementation ----
ScanCount := ScanCount + 1;
IF ResetStats THEN
	RoundsStarted := 0; RoundsDone := 0; Skipped := 0; SkippedOffline := 0; PartsDone := 0; TimeoutCount := 0;
	OverflowCount := 0; MaxBuildUs := 0; SumBuildUs := 0; MaxSendUs := 0; SumSendUs := 0; MaxSendScans := 0;
	SumSendScans := 0; MaxLateUs := 0; MaxPushUs := 0; SumPushUs := 0; MaxRoundsActive := 0; UntrackedCount := 0;
END_IF

// What left the block since the last scan
ServiceRounds();

// Schedule: one round per Period, on a fixed grid from the scan that enabled the stream
NowTimeUs := NowUs();
PeriodUs := TIME_TO_ULINT(Period) * 1000;
IF NOT IsEnabled OR PeriodUs < MIN_PERIOD_US THEN
	IsScheduled := FALSE;
ELSIF NOT IsScheduled THEN
	IsScheduled := TRUE;
	NextDueUs := NowTimeUs;
END_IF
IsDue := FALSE;
IF IsScheduled AND NowTimeUs + ToleranceUs >= NextDueUs THEN
	IsDue := TRUE;
	DueUs := NextDueUs;
	NextDueUs := NextDueUs + PeriodUs;
	// a scan so late that whole periods passed: those are lost as well
	WHILE NowTimeUs + ToleranceUs >= NextDueUs DO
		NextDueUs := NextDueUs + PeriodUs;
		Skipped := Skipped + 1;
	END_WHILE
END_IF

IF IsDue THEN
	IF NOT PLC_PRG.IsBrokerConnected AND NOT IsPushOffline THEN
		SkippedOffline := SkippedOffline + 1;
	ELSIF FirstTag >= 1 AND LastTag >= FirstTag AND LastTag <= BOOL_COUNT + INT_COUNT + REAL_COUNT
		AND TagsPerMessage >= 1 THEN
		Round := Round + 1;
		RoundsStarted := RoundsStarted + 1;
		IF NowTimeUs > DueUs THEN
			MaxLateUs := MAX(MaxLateUs, ULINT_TO_UDINT(NowTimeUs - DueUs));
		END_IF
		StepStartUs := NowUs();
		// New values for this stream's tags: ScaleTest.UpdateValues' formulas with Round for Sequence
		FOR Tag := FirstTag TO LastTag DO
			IF Tag <= BOOL_COUNT THEN
				Bools[Tag] := ((UINT_TO_UDINT(Tag) + Round) MOD 3) = 0;
			ELSIF Tag <= BOOL_COUNT + INT_COUNT THEN
				Kind := UINT_TO_UDINT(Tag - BOOL_COUNT);
				Ints[Kind] := UDINT_TO_DINT((Kind * 37 + Round) MOD 20000) - 10000;
			ELSE
				Kind := UINT_TO_UDINT(Tag - BOOL_COUNT - INT_COUNT);
				Reals[Kind] := DINT_TO_REAL(UDINT_TO_DINT((Kind * 1237 + Round * 17) MOD 200000) - 100000) / 100.0;
			END_IF
		END_FOR
		SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := StampMs);
		StampMs := LINT_TO_ULINT(ULINT_TO_LINT(StampMs) + ClockSync.OffsetMs);   // UTC, see ClockSync
		StampText := ULINT_TO_STRING(StampMs);

		// Every part of the round, back to back in Data (as FB_MixedStream)
		RoundParts := (LastTag - FirstTag + TagsPerMessage) / TagsPerMessage;
		IsBuildOk := RoundParts <= MAX_PARTS;
		Used := 0;
		PartFirst := FirstTag;
		Part := 0;
		WHILE IsBuildOk AND Part < RoundParts DO
			PartStart[Part] := Used;
			Header := CONCAT(CONCAT(CONCAT('MIX:', StreamId), ':'), UDINT_TO_STRING(Round));
			Header := CONCAT(CONCAT(CONCAT(Header, ':'), UINT_TO_STRING(Part)), ':');
			Header := CONCAT(CONCAT(CONCAT(CONCAT(Header, UINT_TO_STRING(RoundParts)), ':'), StampText), '$N');
			IsBuildOk := AppendZ(pBuffer := ADR(Data), Capacity := SIZEOF(Data), pText := ADR(Header), Used := Used);
			PartLast := MIN(LastTag, PartFirst + TagsPerMessage - 1);
			Tag := PartFirst;
			WHILE IsBuildOk AND Tag <= PartLast DO
				// formatted as ScaleTest.BuildTag formats each type
				IF Tag <= BOOL_COUNT THEN
					ValueText := SEL(Bools[Tag], '0', '1');
				ELSIF Tag <= BOOL_COUNT + INT_COUNT THEN
					ValueText := DINT_TO_STRING(Ints[Tag - BOOL_COUNT]);
				ELSE
					RealValue := Reals[Tag - BOOL_COUNT - INT_COUNT];
					ValueText := REAL_TO_STRING(DINT_TO_REAL(TRUNC(RealValue * 100.0 + SEL(RealValue >= 0.0, -0.5, 0.5))) / 100.0);
				END_IF
				IsBuildOk := AppendZ(pBuffer := ADR(Data), Capacity := SIZEOF(Data), pText := ADR(ScaleTest.Names[Tag]), Used := Used)
					AND_THEN AppendZ(pBuffer := ADR(Data), Capacity := SIZEOF(Data), pText := ADR(':'), Used := Used)
					AND_THEN AppendZ(pBuffer := ADR(Data), Capacity := SIZEOF(Data), pText := ADR(ValueText), Used := Used)
					AND_THEN AppendZ(pBuffer := ADR(Data), Capacity := SIZEOF(Data), pText := ADR('$N'), Used := Used);
				Tag := Tag + 1;
			END_WHILE
			PartLength[Part] := Used - PartStart[Part];
			PartFirst := PartLast + 1;
			Part := Part + 1;
		END_WHILE
		LastBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		MaxBuildUs := MAX(MaxBuildUs, LastBuildUs);
		SumBuildUs := SumBuildUs + LastBuildUs;
		LastBytes := Used;
		LastParts := RoundParts;
		IF IsBuildOk THEN
			// Every part to the block, in order; the block hands them to the client in its call after both streams
			RequestUs := NowUs();
			RoundPushed := 0;
			FOR Part := 0 TO RoundParts - 1 DO
				IF Sfw.Push(Topic := ADR(Topic), Payload := ADR(Data[PartStart[Part]]), Length := PartLength[Part]) THEN
					RoundPushed := RoundPushed + 1;
				ELSE
					TimeoutCount := TimeoutCount + 1;
				END_IF
			END_FOR
			LastPushUs := ULINT_TO_UDINT(NowUs() - RequestUs);
			MaxPushUs := MAX(MaxPushUs, LastPushUs);
			SumPushUs := SumPushUs + LastPushUs;
			IF TrackCount >= MAX_TRACKED THEN
				// the oldest round is no longer timed; the newest still is, so IsRoundActive stays right
				TrackHead := (TrackHead + 1) MOD MAX_TRACKED;
				TrackCount := TrackCount - 1;
				UntrackedCount := UntrackedCount + 1;
			END_IF
			Index := (TrackHead + TrackCount) MOD MAX_TRACKED;
			TrackRequestUs[Index] := RequestUs;
			TrackPushMs[Index] := SysTimeCore.SysTimeGetMs();	// not before any part's push time in the block
			TrackScan[Index] := ScanCount;
			TrackParts[Index] := RoundPushed;
			TrackCount := TrackCount + 1;
			MaxRoundsActive := MAX(MaxRoundsActive, TrackCount);
			IsRoundActive := TRUE;
			// no ServiceRounds here: the block's outputs are fresh only after its call, later in this scan
		ELSE
			OverflowCount := OverflowCount + 1;
		END_IF
	END_IF
END_IF
