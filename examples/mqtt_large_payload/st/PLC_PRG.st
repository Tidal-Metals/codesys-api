PROGRAM PLC_PRG
// Publishes one large MQTT payload with the unmodified Stefan Dreyer MQTT 1.2.0.7 library.
// Optionally also publishes a CONCAT-built copy of the same text, which shows where the
// 255-character cap comes from; it is off by default so the timings match production.
// The *Us/*Cycles variables measure what large payloads cost the PLC; write ResetStats to clear maxima.
VAR
	MqttLink : MQTT.MQTT_IN_OUT;          // not "Mqtt": ST names are case-insensitive and would hide the MQTT namespace
	LargePublisher : MQTT.MQTTPublish;
	ConcatPublisher : MQTT.MQTTPublish;
	IsInitialized : BOOL;

	// Settings, writable online
	BrokerUrl : STRING(64) := '192.168.50.240:1883';
	LargeTopic : STRING(64) := 'raw_data_demo';
	ConcatTopic : STRING(64) := 'raw_data_demo/concat';
	ValueCount : UINT := 500;            // values per message
	PublishPeriod : TIME := T#1S;        // BCNF publishes once a second
	IsRealFormat : BOOL := TRUE;         // two-decimal REALs formatted the way BCNF does; FALSE = integers
	IsQos1 : BOOL := FALSE;              // BCNF publishes at QoS 0
	IsConcatControlEnabled : BOOL;       // the 255-character demonstration; not production work
	IsBcnfEveryScanEnabled : BOOL;       // run BCNF's StringPublication (verbatim copy) every scan, as BCNF does
	IsTagValueEnabled : BOOL;            // publish BCNF's values as tag:value lines once a second
	TagValueTopic : STRING(64) := 'raw_data_demo/tagvalue';
	PublishTimer : TON;

	LargePayload : STRING(30000);        // about 1,500 two-decimal values
	LargeUsed : UDINT;
	ConcatPayload : STRING(8000);        // the "bigger string" approach that still truncates
	Line : STRING(80);                   // one short line; CONCAT is fine below 255
	PublishQoS : MQTT.QoS;

	IsLargeRequested : BOOL;
	IsConcatRequested : BOOL;
	IsBuildOk : BOOL;
	Sequence : UDINT;
	Index : UINT;
	ValueIndex : UINT;
	RealValue : REAL;

	// Diagnostics, readable online
	IsBrokerConnected : BOOL;
	LargeSentCount : UDINT;
	ConcatSentCount : UDINT;
	TimeoutCount : UDINT;
	OverflowCount : UDINT;
	SkippedBusyCount : UDINT;
	LastLargeLength : UDINT;
	LastConcatLength : UDINT;

	// Performance, microseconds unless named *Cycles
	ResetStats : BOOL;
	CycleStartUs : ULINT;
	PreviousCycleStartUs : ULINT;
	StepStartUs : ULINT;
	LargeRequestUs : ULINT;
	LastLargeBuildUs : UDINT;
	MaxLargeBuildUs : UDINT;
	LastConcatBuildUs : UDINT;
	MaxConcatBuildUs : UDINT;
	ClientUs : UDINT;
	MaxClientUs : UDINT;
	CycleUs : UDINT;
	MaxCycleUs : UDINT;
	IntervalUs : UDINT;
	MaxIntervalUs : UDINT;
	MinIntervalUs : UDINT := 16#FFFFFFFF;
	LargeBusyCycles : UDINT;
	LastPublishCycles : UDINT;
	MaxPublishCycles : UDINT;
	LastPublishUs : UDINT;
	MaxPublishUs : UDINT;
	LastBcnfBuildUs : UDINT;             // one call of BCNF's StringPublication copy
	MaxBcnfBuildUs : UDINT;
	BcnfBuildCount : UDINT;
	BcnfBuildTotalUs : ULINT;            // average = BcnfBuildTotalUs / BcnfBuildCount

	// BCNF's values in tag:value format (BcnfStringPublicationCopy.BuildTagValue), built once per publish
	TagValuePublisher : MQTT.MQTTPublish;
	TagValueTimer : TON;
	TagValueQoS : MQTT.QoS;
	IsTagValueRequested : BOOL;
	TagValueRequestUs : ULINT;
	TagValueBusyCycles : UDINT;
	TagValueSentCount : UDINT;
	TagValueTimeoutCount : UDINT;
	LastTagValueLength : UDINT;
	LastTagValueBuildUs : UDINT;
	MaxTagValueBuildUs : UDINT;
	TagValueBuildCount : UDINT;
	TagValueBuildTotalUs : ULINT;
	LastTagValuePublishUs : UDINT;
	MaxTagValuePublishUs : UDINT;
	LastTagValuePublishCycles : UDINT;
	MaxTagValuePublishCycles : UDINT;
END_VAR
// ---- implementation ----
CycleStartUs := NowUs();
IF ResetStats THEN
	ResetStats := FALSE;
	MaxLargeBuildUs := 0;
	MaxConcatBuildUs := 0;
	MaxClientUs := 0;
	MaxCycleUs := 0;
	MaxIntervalUs := 0;
	MinIntervalUs := 16#FFFFFFFF;
	MaxPublishCycles := 0;
	MaxPublishUs := 0;
	PreviousCycleStartUs := 0;
	MaxBcnfBuildUs := 0;
	BcnfBuildCount := 0;
	BcnfBuildTotalUs := 0;
	MaxTagValueBuildUs := 0;
	TagValueBuildCount := 0;
	TagValueBuildTotalUs := 0;
	MaxTagValuePublishUs := 0;
	MaxTagValuePublishCycles := 0;
END_IF
IF PreviousCycleStartUs <> 0 THEN
	IntervalUs := ULINT_TO_UDINT(CycleStartUs - PreviousCycleStartUs);
	MaxIntervalUs := MAX(MaxIntervalUs, IntervalUs);
	MinIntervalUs := MIN(MinIntervalUs, IntervalUs);
END_IF
PreviousCycleStartUs := CycleStartUs;

MqttLink.ClientID := 'BENCH_MQTT_DEMO';
StepStartUs := NowUs();
MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ENABLE := TRUE, URL := BrokerUrl, TIMEOUT := T#10S, TLS := FALSE);
ClientUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
MaxClientUs := MAX(MaxClientUs, ClientUs);
IsBrokerConnected := MqttLink.BROKER_CONNECTED;

IF NOT IsInitialized THEN
	IsInitialized := TRUE;
	LargePublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);
	ConcatPublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);
	TagValuePublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);
END_IF

PublishTimer(IN := NOT PublishTimer.Q, PT := PublishPeriod);

// The library reads the payload through its pointer over several cycles,
// so a payload is only rebuilt once its previous publish has finished.
IF PublishTimer.Q AND IsBrokerConnected THEN
	IF IsLargeRequested OR IsConcatRequested THEN
		SkippedBusyCount := SkippedBusyCount + 1;
	ELSE
		Sequence := Sequence + 1;
		// Lines: DEMO_SEQ, DEMO_COUNT, DEMO_FORMAT, DEMO_V1..DEMO_Vn, DEMO_END (see BuildLine).
		StepStartUs := NowUs();
		LargeUsed := 0;
		LargePayload := '';
		IsBuildOk := TRUE;
		FOR Index := 0 TO ValueCount + 3 DO
			BuildLine();
			IsBuildOk := IsBuildOk AND AppendText(pBuffer := ADR(LargePayload), Capacity := SIZEOF(LargePayload), Text := Line, Used := LargeUsed);
		END_FOR
		LastLargeBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		MaxLargeBuildUs := MAX(MaxLargeBuildUs, LastLargeBuildUs);

		ConcatPayload := '';
		LastConcatBuildUs := 0;
		IF IsConcatControlEnabled THEN
			StepStartUs := NowUs();
			FOR Index := 0 TO ValueCount + 3 DO
				BuildLine();
				ConcatPayload := CONCAT(ConcatPayload, Line);
			END_FOR
			LastConcatBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
			MaxConcatBuildUs := MAX(MaxConcatBuildUs, LastConcatBuildUs);
		END_IF

		IF NOT IsBuildOk THEN
			OverflowCount := OverflowCount + 1;
		END_IF
		LastLargeLength := LargeUsed;
		LastConcatLength := INT_TO_UDINT(LEN(ConcatPayload));
		IF IsQos1 THEN
			PublishQoS := MQTT.QoS.AtLeastOnce;
		ELSE
			PublishQoS := MQTT.QoS.AtMostOnce;
		END_IF
		IsLargeRequested := IsBuildOk;
		IsConcatRequested := IsConcatControlEnabled;
		LargeRequestUs := NowUs();
		LargeBusyCycles := 0;
	END_IF
END_IF

LargePublisher(
	Topic := ADR(LargeTopic),
	PayloadString := ADR(LargePayload),
	PublishAsString := TRUE,
	QoSIn := PublishQoS,
	MRetain := FALSE,
	send := IsLargeRequested);

ConcatPublisher(
	Topic := ADR(ConcatTopic),
	PayloadString := ADR(ConcatPayload),
	PublishAsString := TRUE,
	QoSIn := PublishQoS,
	MRetain := FALSE,
	send := IsConcatRequested AND NOT IsLargeRequested);

IF IsLargeRequested THEN
	LargeBusyCycles := LargeBusyCycles + 1;
END_IF
IF LargePublisher.done THEN
	IsLargeRequested := FALSE;
	LargeSentCount := LargeSentCount + 1;
	// Request to done: PUBACK at QoS 1, payload handed to TCP at QoS 0; includes the scans spent copying it out.
	LastPublishUs := ULINT_TO_UDINT(NowUs() - LargeRequestUs);
	MaxPublishUs := MAX(MaxPublishUs, LastPublishUs);
	LastPublishCycles := LargeBusyCycles;
	MaxPublishCycles := MAX(MaxPublishCycles, LastPublishCycles);
END_IF
IF ConcatPublisher.done THEN
	IsConcatRequested := FALSE;
	ConcatSentCount := ConcatSentCount + 1;
END_IF
IF LargePublisher.SendTimeout OR ConcatPublisher.SendTimeout THEN
	TimeoutCount := TimeoutCount + 1;
	IsLargeRequested := FALSE;
	IsConcatRequested := FALSE;
END_IF

// BCNF's values as tag:value lines: built only in the scan that publishes, sent as one message.
IF IsQos1 THEN
	TagValueQoS := MQTT.QoS.AtLeastOnce;
ELSE
	TagValueQoS := MQTT.QoS.AtMostOnce;
END_IF
TagValueTimer(IN := IsTagValueEnabled AND NOT TagValueTimer.Q, PT := T#1S);
IF TagValueTimer.Q AND IsBrokerConnected AND NOT IsTagValueRequested THEN
	StepStartUs := NowUs();
	BcnfStringPublicationCopy.BuildTagValue();
	LastTagValueBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
	MaxTagValueBuildUs := MAX(MaxTagValueBuildUs, LastTagValueBuildUs);
	TagValueBuildCount := TagValueBuildCount + 1;
	TagValueBuildTotalUs := TagValueBuildTotalUs + LastTagValueBuildUs;
	LastTagValueLength := BcnfStringPublicationCopy.TagValueUsed;
	IsTagValueRequested := BcnfStringPublicationCopy.IsTagValueBuildOk;
	TagValueRequestUs := NowUs();
	TagValueBusyCycles := 0;
END_IF
TagValuePublisher(
	Topic := ADR(TagValueTopic),
	PayloadString := ADR(BcnfStringPublicationCopy.TagValuePayload),
	PublishAsString := TRUE,
	QoSIn := TagValueQoS,
	MRetain := FALSE,
	send := IsTagValueRequested);
IF IsTagValueRequested THEN
	TagValueBusyCycles := TagValueBusyCycles + 1;
END_IF
IF TagValuePublisher.done THEN
	IsTagValueRequested := FALSE;
	TagValueSentCount := TagValueSentCount + 1;
	LastTagValuePublishUs := ULINT_TO_UDINT(NowUs() - TagValueRequestUs);
	MaxTagValuePublishUs := MAX(MaxTagValuePublishUs, LastTagValuePublishUs);
	LastTagValuePublishCycles := TagValueBusyCycles;
	MaxTagValuePublishCycles := MAX(MaxTagValuePublishCycles, LastTagValuePublishCycles);
END_IF
IF TagValuePublisher.SendTimeout THEN
	TagValueTimeoutCount := TagValueTimeoutCount + 1;
	IsTagValueRequested := FALSE;
END_IF

// What BCNF pays today: its payload strings are rebuilt in every scan, not only when publishing.
IF IsBcnfEveryScanEnabled THEN
	StepStartUs := NowUs();
	BcnfStringPublicationCopy();
	LastBcnfBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
	MaxBcnfBuildUs := MAX(MaxBcnfBuildUs, LastBcnfBuildUs);
	BcnfBuildCount := BcnfBuildCount + 1;
	BcnfBuildTotalUs := BcnfBuildTotalUs + LastBcnfBuildUs;
END_IF

CycleUs := ULINT_TO_UDINT(NowUs() - CycleStartUs);
MaxCycleUs := MAX(MaxCycleUs, CycleUs);
