FUNCTION_BLOCK FB_MixedStream
// One periodic stream of the mixed-rate test (MixedTest, mixed_rate_test.py). Every Period, tags FirstTag..LastTag
// (ScaleTest's numbering, names and value formulas, with this stream's Round in place of ScaleTest's Sequence) go out
// with full values as tag:value lines, TagsPerMessage tags per message, through up to Publishers MQTTPublish
// instances. Each message: "MIX:<StreamId>:<round>:<part>:<parts>:<UTC ms>" and then one "<tag>:<value>" line per tag.
// A period that comes due while the previous round is still in flight is skipped (Skipped): its values never leave
// the PLC. That count is what "keeping up" means here. Each scan first collects finished parts (ServicePool), then
// checks the schedule; a done publisher is re-armed and given the next part in the same scan, as in SplitTest.
VAR CONSTANT
	MAX_BYTES : UDINT := 32000;
	MAX_PARTS : UINT := 64;
	MAX_PUBLISHERS : UINT := 24;
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
	Publishers : UINT;                      // 1 .. MAX_PUBLISHERS
	Period : TIME;
	QoSLevel : BYTE;                        // 0 or 1 (2 works too)
	Topic : STRING(64);
	ToleranceUs : ULINT;                    // a period is due this much early (task jitter)
	ResetStats : BOOL;
END_VAR
VAR_OUTPUT
	IsRoundActive : BOOL;                   // a round's messages are in flight
END_VAR
VAR
	// Results, read online (microseconds unless named *Scans/*Count)
	Round : UDINT;                          // rounds started since download (not reset; the broker check uses it)
	RoundsStarted : UDINT;
	RoundsDone : UDINT;
	Skipped : UDINT;                        // periods lost because the previous round was still in flight
	SkippedOffline : UDINT;                 // periods lost because the broker was not connected
	PartsDone : UDINT;
	TimeoutCount : UDINT;                   // parts given up: SendTimeout or Rejected
	OverflowCount : UDINT;                  // rounds that did not fit MAX_BYTES / MAX_PARTS (not sent)
	LastBytes : UDINT;                      // all parts of the last round, headers included
	LastParts : UINT;
	LastBuildUs : UDINT;                    // value update + formatting of the whole round, in its first scan
	MaxBuildUs : UDINT;
	SumBuildUs : ULINT;
	LastSendUs : UDINT;                     // build finished -> last part done (handed to TCP at QoS 0, PUBACK at QoS 1)
	MaxSendUs : UDINT;
	SumSendUs : ULINT;
	LastSendScans : UDINT;                  // scans from the build to the last done (0 = in the same scan)
	MaxSendScans : UDINT;
	SumSendScans : ULINT;
	MaxLateUs : UDINT;                      // how late after its due time a round started (scan phase)

	// State
	Pool : ARRAY[1..MAX_PUBLISHERS] OF MQTT.MQTTPublish;
	IsRequested : ARRAY[1..MAX_PUBLISHERS] OF BOOL;
	PoolOffset : ARRAY[1..MAX_PUBLISHERS] OF UDINT;
	PoolLength : ARRAY[1..MAX_PUBLISHERS] OF UDINT;
	PartStart : ARRAY[0..MAX_PARTS - 1] OF UDINT;
	PartLength : ARRAY[0..MAX_PARTS - 1] OF UDINT;
	Data : ARRAY[0..MAX_BYTES - 1] OF BYTE;
	Bools : ARRAY[1..BOOL_COUNT] OF BOOL;
	Ints : ARRAY[1..INT_COUNT] OF DINT;
	Reals : ARRAY[1..REAL_COUNT] OF REAL;
	IsReady : BOOL;
	IsScheduled : BOOL;
	IsDue : BOOL;
	IsBuildOk : BOOL;
	NowTimeUs : ULINT;
	PeriodUs : ULINT;
	NextDueUs : ULINT;
	DueUs : ULINT;
	StepStartUs : ULINT;
	RequestUs : ULINT;
	ScanCount : UDINT;
	RequestScan : UDINT;
	RoundParts : UINT;
	PartsFinished : UINT;
	NextPart : UINT;
	PoolInUse : UINT;
	PublishQoS : MQTT.QoS;
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
IF NOT IsReady THEN
	IsReady := TRUE;
	FOR Index := 1 TO MAX_PUBLISHERS DO
		Pool[Index].SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	END_FOR
END_IF
IF ResetStats THEN
	RoundsStarted := 0; RoundsDone := 0; Skipped := 0; SkippedOffline := 0; PartsDone := 0; TimeoutCount := 0;
	OverflowCount := 0; MaxBuildUs := 0; SumBuildUs := 0; MaxSendUs := 0; SumSendUs := 0; MaxSendScans := 0;
	SumSendScans := 0; MaxLateUs := 0;
END_IF

// What finished since the last scan, before deciding whether the stream is still busy
ServicePool();

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
	IF NOT PLC_PRG.IsBrokerConnected THEN
		SkippedOffline := SkippedOffline + 1;
	ELSIF IsRoundActive THEN
		Skipped := Skipped + 1;
	ELSIF FirstTag >= 1 AND LastTag >= FirstTag AND LastTag <= BOOL_COUNT + INT_COUNT + REAL_COUNT
		AND TagsPerMessage >= 1 AND Publishers >= 1 AND Publishers <= MAX_PUBLISHERS THEN
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

		// Every part of the round, back to back in Data
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
			CASE QoSLevel OF
				1: PublishQoS := MQTT.QoS.AtLeastOnce;
				2: PublishQoS := MQTT.QoS.ExactlyOnce;
			ELSE
				PublishQoS := MQTT.QoS.AtMostOnce;
			END_CASE
			PoolInUse := MIN(Publishers, RoundParts);
			NextPart := 0;
			PartsFinished := 0;
			RequestUs := NowUs();
			RequestScan := ScanCount;
			IsRoundActive := TRUE;
			ServicePool();	// request the new round's first parts in this scan
		ELSE
			OverflowCount := OverflowCount + 1;
		END_IF
	END_IF
END_IF

