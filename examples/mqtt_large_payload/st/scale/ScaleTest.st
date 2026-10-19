PROGRAM ScaleTest
// Scale test for the new system: 2,000 tags (1,000 BOOL, 500 DINT, 500 REAL) with 7-9 byte names,
// published once a second either as "tag:value" lines or as publish-map groups "[Gn, v1, v2, ...]".
// The build can be spread over several scans (TagsPerScan). Counters are readable online.
VAR CONSTANT
	TAG_COUNT : UINT := 2000;
	BOOL_COUNT : UINT := 1000;
	INT_COUNT : UINT := 500;
	REAL_COUNT : UINT := 500;
	GROUP_SIZE : UINT := 100;           // publish-map values per group line
END_VAR
VAR
	// Settings, writable online
	IsEnabled : BOOL;
	IsTagValueFormat : BOOL := TRUE;    // FALSE = publish-map groups
	TagsPerScan : UINT := 2000;         // 2000 = whole build in one scan
	IsQos1 : BOOL;
	PublishPeriod : TIME := T#1S;
	Topic : STRING(64) := 'raw_data_demo/scale';
	ResetStats : BOOL;
	OnlyKind : INT;                     // measurement aid: 0 = all, 1 = BOOL only, 2 = DINT only, 3 = REAL only, 4 = none
	RealDeadband : REAL := 0.5;         // report-by-exception: REAL change that counts

	// Report-by-exception: last values sent, and what changed since (DetectChanges)
	LastBools : ARRAY[1..BOOL_COUNT] OF BOOL;
	LastInts : ARRAY[1..INT_COUNT] OF DINT;
	LastReals : ARRAY[1..REAL_COUNT] OF REAL;
	ChangedBools : UINT;
	ChangedInts : UINT;
	ChangedReals : UINT;
	ChangeDetectUs : UDINT;
	MaxChangeDetectUs : UDINT;
	Kind : INT;

	// Data: names as constant tag names would be stored, values refreshed every publish
	Names : ARRAY[1..TAG_COUNT] OF STRING(9);
	Bools : ARRAY[1..BOOL_COUNT] OF BOOL;
	Ints : ARRAY[1..INT_COUNT] OF DINT;
	Reals : ARRAY[1..REAL_COUNT] OF REAL;
	Prefixes : ARRAY[0..11] OF STRING(3) := ['TT', 'PT', 'FT', 'LT', 'XV', 'HS', 'ZS', 'PIT', 'FIT', 'TIT', 'LIT', 'AIT'];
	Suffixes : ARRAY[0..3] OF STRING(1) := ['A', 'B', 'S', 'V'];
	Payload : STRING(40000);
	Used : UDINT;
	ValueText : STRING(40);
	Header : STRING(40);
	RealValue : REAL;

	// State
	IsNamesReady : BOOL;
	IsPublisherReady : BOOL;
	IsBuilding : BOOL;
	IsRequested : BOOL;
	IsBuildOk : BOOL;
	NextTag : UINT;
	LastTag : UINT;
	Index : UINT;
	Sequence : UDINT;
	Timer : TON;
	Publisher : MQTT.MQTTPublish;
	PublishQoS : MQTT.QoS;
	StepStartUs : ULINT;
	ScanBuildUs : UDINT;
	RequestUs : ULINT;
	BusyCycles : UDINT;

	// Statistics, readable online (microseconds unless named *Cycles/*Scans/*Count)
	NamesInitUs : UDINT;
	ValueUpdateUs : UDINT;
	LastPayloadLength : UDINT;
	LastBuildUs : UDINT;                // all build scans of the last message added together
	MaxBuildUs : UDINT;
	BuildTotalUs : ULINT;
	BuildCount : UDINT;
	MaxBuildScanUs : UDINT;             // the most build time spent in any one scan
	LastBuildScans : UDINT;
	LastPublishUs : UDINT;              // build finished -> done (TCP at QoS 0, PUBACK at QoS 1)
	MaxPublishUs : UDINT;
	LastPublishCycles : UDINT;
	MaxPublishCycles : UDINT;
	SentCount : UDINT;
	TimeoutCount : UDINT;
	OverflowCount : UDINT;
	SkippedBusyCount : UDINT;
END_VAR
// ---- implementation ----
IF NOT IsPublisherReady THEN
	IsPublisherReady := TRUE;
	Publisher.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
END_IF
IF NOT IsNamesReady THEN
	// One-time: 'TT-1001', 'FIT-1009A', ... (7-9 bytes), standing in for constant tag names.
	StepStartUs := NowUs();
	FOR Index := 1 TO TAG_COUNT DO
		Names[Index] := CONCAT(CONCAT(Prefixes[(Index - 1) MOD 12], '-'), UINT_TO_STRING(1000 + Index));
		IF Index MOD 3 = 0 THEN
			Names[Index] := CONCAT(Names[Index], Suffixes[(Index / 3) MOD 4]);
		END_IF
	END_FOR
	NamesInitUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
	IsNamesReady := TRUE;
END_IF
IF ResetStats THEN
	ResetStats := FALSE;
	MaxBuildUs := 0;
	BuildTotalUs := 0;
	BuildCount := 0;
	MaxBuildScanUs := 0;
	MaxPublishUs := 0;
	MaxPublishCycles := 0;
	MaxChangeDetectUs := 0;
END_IF
IF IsQos1 THEN
	PublishQoS := MQTT.QoS.AtLeastOnce;
ELSE
	PublishQoS := MQTT.QoS.AtMostOnce;
END_IF

Timer(IN := IsEnabled AND NOT Timer.Q, PT := PublishPeriod);
IF Timer.Q AND PLC_PRG.IsBrokerConnected THEN
	IF IsBuilding OR IsRequested THEN
		SkippedBusyCount := SkippedBusyCount + 1;
	ELSE
		Sequence := Sequence + 1;
		StepStartUs := NowUs();
		UpdateValues();
		ValueUpdateUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		StepStartUs := NowUs();
		DetectChanges();
		ChangeDetectUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		MaxChangeDetectUs := MAX(MaxChangeDetectUs, ChangeDetectUs);
		StepStartUs := NowUs();
		Used := 0;
		Payload := '';
		IF IsTagValueFormat THEN
			Header := CONCAT(CONCAT('SCALE-SEQ:', UDINT_TO_STRING(Sequence)), '$N');
		ELSE
			Header := CONCAT(CONCAT('[SCALE_SEQ, ', UDINT_TO_STRING(Sequence)), ']$N');
		END_IF
		IsBuildOk := AppendZ(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), pText := ADR(Header), Used := Used);
		LastBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		LastBuildScans := 0;
		NextTag := 1;
		IsBuilding := TRUE;
	END_IF
END_IF

// Build TagsPerScan tags per scan until the message is complete.
IF IsBuilding THEN
	StepStartUs := NowUs();
	LastTag := MIN(TAG_COUNT, NextTag + MAX(TagsPerScan, 1) - 1);
	FOR Index := NextTag TO LastTag DO
		BuildTag();
	END_FOR
	NextTag := LastTag + 1;
	ScanBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
	LastBuildUs := LastBuildUs + ScanBuildUs;
	MaxBuildScanUs := MAX(MaxBuildScanUs, ScanBuildUs);
	LastBuildScans := LastBuildScans + 1;
	IF NextTag > TAG_COUNT THEN
		IsBuilding := FALSE;
		LastPayloadLength := Used;
		MaxBuildUs := MAX(MaxBuildUs, LastBuildUs);
		BuildTotalUs := BuildTotalUs + LastBuildUs;
		BuildCount := BuildCount + 1;
		IF IsBuildOk THEN
			IsRequested := TRUE;
			RequestUs := NowUs();
			BusyCycles := 0;
		ELSE
			OverflowCount := OverflowCount + 1;
		END_IF
	END_IF
END_IF

Publisher(
	Topic := ADR(Topic),
	PayloadString := ADR(Payload),
	PublishAsString := TRUE,
	QoSIn := PublishQoS,
	MRetain := FALSE,
	send := IsRequested);
IF IsRequested THEN
	BusyCycles := BusyCycles + 1;
END_IF
IF Publisher.done THEN
	IsRequested := FALSE;
	SentCount := SentCount + 1;
	LastPublishUs := ULINT_TO_UDINT(NowUs() - RequestUs);
	MaxPublishUs := MAX(MaxPublishUs, LastPublishUs);
	LastPublishCycles := BusyCycles;
	MaxPublishCycles := MAX(MaxPublishCycles, LastPublishCycles);
END_IF
IF Publisher.SendTimeout THEN
	TimeoutCount := TimeoutCount + 1;
	IsRequested := FALSE;
END_IF
