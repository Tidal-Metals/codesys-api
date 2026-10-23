PROGRAM BcnfComms
// BCNF's MQTT path (PLC_BCNF_4_16_26: POU1, FirstSubscription, FirstPublish) on the bench, nearly verbatim: two client
// connections in one PLC (PUB and SUB, both called every scan), CallbackCollector + ReceiveString subscriptions at
// QoS 2, seven QoS 0 string publishers once a second, plus one MQTTState on the PUB connection. Topics are moved under
// raw_data_demo/bcnf/. Idle (both clients disabled) unless IsEnabled; bcnf_test.py drives it.
VAR
	IsEnabled : BOOL;                       // written online
	BrokerUrl : STRING(250) := '192.168.50.240:1883';
	MQTT_PUBLISH : MQTT.MQTT_IN_OUT;
	MQTT_SUBSCRIBE : MQTT.MQTT_IN_OUT;
	FirstSubscription : BenchFirstSubscription;
	FirstPublish : BenchFirstPublish;
	currentMessage : STRING(255);
	CurrentMqttMessageReady : STRING(255);
	// What bcnf_test.py reads
	PubConnected : BOOL;
	SubConnected : BOOL;
	LastMessage : STRING(255);
	LastReady : STRING(255);
	CommandChanges : UDINT;                 // currentMessage changed: one per command when commands are paced
	ReadyChanges : UDINT;
	// The seven interlock strings BCNF publishes, here changing every scan
	Data : ARRAY[1..7] OF STRING(255);
	Scan : UDINT;
	Index : INT;
	// MQTTState (its request now also ends on Rejected)
	StateFlag : BOOL;                       // written online: each change publishes flag:on / flag:off at QoS 1
	StateBlock : MQTT.MQTTState;
	StateTopic : STRING(64) := 'raw_data_demo/bcnf/state';
	StateName : STRING(16) := 'flag';
	StateOn : STRING(8) := 'on';
	StateOff : STRING(8) := 'off';
	IsStateReady : BOOL;
	// Not in BCNF: a '#' subscription, which must also match its parent level (raw_data_demo/bcnf/wild itself)
	WildSub : MQTT.MQTTSubscribe;
	WildCollector : MQTT.CallbackCollector;
	WildReceiver : MQTT.ReceiveString;          // exactly raw_data_demo/bcnf/wild (ReceiveString compares the whole topic)
	WildChildReceiver : MQTT.ReceiveString;     // exactly raw_data_demo/bcnf/wild/child
	LastWildChild : STRING(255);
	IsWildReady : BOOL;
	WildMessage : STRING(255);
	LastWild : STRING(255);
	WildChanges : UDINT;
END_VAR
// ---- implementation ----
// BCNF calls both clients every scan (its subscriptionInitialized flag is never set); so does this, with ENABLE
// following IsEnabled so that disabling disconnects them
MQTT_PUBLISH.ClientID := 'BENCH_BCNF_PUB';
MQTT_PUBLISH.clientFB(MQTT_IN_OUT := MQTT_PUBLISH, ENABLE := IsEnabled, URL := BrokerUrl, TIMEOUT := T#10S, TLS := FALSE);
MQTT_SUBSCRIBE.ClientID := 'BENCH_BCNF_SUB';
MQTT_SUBSCRIBE.clientFB(MQTT_IN_OUT := MQTT_SUBSCRIBE, ENABLE := IsEnabled, URL := BrokerUrl, TIMEOUT := T#10S, TLS := FALSE);
PubConnected := MQTT_PUBLISH.BROKER_CONNECTED;
SubConnected := MQTT_SUBSCRIBE.BROKER_CONNECTED;
IF NOT IsEnabled THEN
	RETURN;
END_IF

FirstSubscription();
currentMessage := FirstSubscription.receiver.MQTTReceived;
CurrentMqttMessageReady := FirstSubscription.receiverReady.MQTTReceived;
IF currentMessage <> LastMessage THEN
	LastMessage := currentMessage;
	CommandChanges := CommandChanges + 1;
END_IF
IF CurrentMqttMessageReady <> LastReady THEN
	LastReady := CurrentMqttMessageReady;
	ReadyChanges := ReadyChanges + 1;
END_IF

Scan := Scan + 1;
FOR Index := 1 TO 7 DO
	Data[Index] := CONCAT(CONCAT('group', INT_TO_STRING(Index)), CONCAT(':', UDINT_TO_STRING(Scan)));
END_FOR
FirstPublish(InterlockData1 := Data[1], InterlockData2 := Data[2], InterlockData3 := Data[3], InterlockData4 := Data[4],
	InterlockData5 := Data[5], InterlockData6 := Data[6], InterlockData7 := Data[7]);

IF NOT IsStateReady THEN
	IsStateReady := TRUE;
	StateBlock.Init(State := ADR(StateFlag), Topic := ADR(StateTopic), StateName := ADR(StateName),
		MQTT_IN_OUT := MQTT_PUBLISH, StateValueOn := ADR(StateOn), StateValueOff := ADR(StateOff),
		QoS := MQTT.QoS.AtLeastOnce, RetainMqtt := FALSE);
END_IF
StateBlock();

IF NOT IsWildReady THEN
	IsWildReady := TRUE;
	WildSub.SetMqttInOut(MQTT_IN_OUT := MQTT_SUBSCRIBE);
	WildCollector.put(instance := WildReceiver);
	WildReceiver.initAsFindTopic(compString := ADR('raw_data_demo/bcnf/wild'), returnHit := TRUE);
	WildCollector.put(instance := WildChildReceiver);
	WildChildReceiver.initAsFindTopic(compString := ADR('raw_data_demo/bcnf/wild/child'), returnHit := TRUE);
END_IF
WildSub(Subscribe := TRUE, Topic := ADR('raw_data_demo/bcnf/wild/#'), QoSSubscribe := MQTT.QoS.AtLeastOnce,
	ExpectingString := TRUE, Callback := WildCollector);
WildMessage := WildReceiver.MQTTReceived;
LastWildChild := WildChildReceiver.MQTTReceived;
IF WildMessage <> LastWild THEN
	LastWild := WildMessage;
	WildChanges := WildChanges + 1;
END_IF
