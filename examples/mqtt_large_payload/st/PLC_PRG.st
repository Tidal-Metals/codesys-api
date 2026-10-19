PROGRAM PLC_PRG
// Publishes one large MQTT payload with the unmodified Stefan Dreyer MQTT 1.2.0.7 library,
// plus a CONCAT-built copy of the same text to show where the 255-character cap comes from.
// The *Us/*Cycles variables measure what large payloads cost the PLC; write ResetStats to clear maxima.
VAR
	MqttLink : MQTT.MQTT_IN_OUT;          // not "Mqtt": ST names are case-insensitive and would hide the MQTT namespace
	LargePublisher : MQTT.MQTTPublish;
	ConcatPublisher : MQTT.MQTTPublish;
	IsInitialized : BOOL;

	BrokerUrl : STRING(64) := '192.168.50.240:1883';
	LargeTopic : STRING(64) := 'raw_data_demo';
	ConcatTopic : STRING(64) := 'raw_data_demo/concat';
	ValueCount : UINT := 500;            // lines per message; writable online
	PublishPeriod : TIME := T#5S;
	PublishTimer : TON;

	LargePayload : STRING(20000);
	LargeUsed : UDINT;
	ConcatPayload : STRING(8000);        // the "bigger string" approach that still truncates
	Line : STRING(80);                   // one short line; CONCAT is fine below 255

	IsLargeRequested : BOOL;
	IsConcatRequested : BOOL;
	IsBuildOk : BOOL;
	Sequence : UDINT;
	Index : UINT;

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
END_IF

PublishTimer(IN := NOT PublishTimer.Q, PT := PublishPeriod);

// The library reads the payload through its pointer over several cycles,
// so a payload is only rebuilt once its previous publish has finished.
IF PublishTimer.Q AND IsBrokerConnected THEN
	IF IsLargeRequested OR IsConcatRequested THEN
		SkippedBusyCount := SkippedBusyCount + 1;
	ELSE
		Sequence := Sequence + 1;
		// Lines: DEMO_SEQ, DEMO_COUNT, DEMO_V1..DEMO_Vn (= Sequence*1000 + i), DEMO_END.
		StepStartUs := NowUs();
		LargeUsed := 0;
		LargePayload := '';
		IsBuildOk := TRUE;
		FOR Index := 0 TO ValueCount + 2 DO
			BuildLine();
			IsBuildOk := IsBuildOk AND AppendText(pBuffer := ADR(LargePayload), Capacity := SIZEOF(LargePayload), Text := Line, Used := LargeUsed);
		END_FOR
		LastLargeBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		MaxLargeBuildUs := MAX(MaxLargeBuildUs, LastLargeBuildUs);

		StepStartUs := NowUs();
		ConcatPayload := '';
		FOR Index := 0 TO ValueCount + 2 DO
			BuildLine();
			ConcatPayload := CONCAT(ConcatPayload, Line);
		END_FOR
		LastConcatBuildUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
		MaxConcatBuildUs := MAX(MaxConcatBuildUs, LastConcatBuildUs);

		IF NOT IsBuildOk THEN
			OverflowCount := OverflowCount + 1;
		END_IF
		LastLargeLength := LargeUsed;
		LastConcatLength := INT_TO_UDINT(LEN(ConcatPayload));
		IsLargeRequested := IsBuildOk;
		IsConcatRequested := TRUE;
		LargeRequestUs := NowUs();
		LargeBusyCycles := 0;
	END_IF
END_IF

LargePublisher(
	Topic := ADR(LargeTopic),
	PayloadString := ADR(LargePayload),
	PublishAsString := TRUE,
	QoSIn := MQTT.QoS.AtLeastOnce,
	MRetain := FALSE,
	send := IsLargeRequested);

ConcatPublisher(
	Topic := ADR(ConcatTopic),
	PayloadString := ADR(ConcatPayload),
	PublishAsString := TRUE,
	QoSIn := MQTT.QoS.AtLeastOnce,
	MRetain := FALSE,
	send := IsConcatRequested AND NOT IsLargeRequested);

IF IsLargeRequested THEN
	LargeBusyCycles := LargeBusyCycles + 1;
END_IF
IF LargePublisher.done THEN
	IsLargeRequested := FALSE;
	LargeSentCount := LargeSentCount + 1;
	// Send request to PUBACK (QoS 1), including the scans spent copying the payload out.
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

CycleUs := ULINT_TO_UDINT(NowUs() - CycleStartUs);
MaxCycleUs := MAX(MaxCycleUs, CycleUs);
