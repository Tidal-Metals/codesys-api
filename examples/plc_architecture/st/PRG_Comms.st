PROGRAM PRG_Comms
// Comms task: lower priority than PRG_Control (e.g. 100 ms). One MQTT client for subscribing and
// publishing. Never touches Tags directly: commands go in through GVL_Tags.Commands, data comes out
// through GVL_Tags.PublishSnapshot, acknowledgements through GVL_Tags.Acks.
VAR CONSTANT
	TAGS_PER_CALL : INT := 250;         // spread a large build over several calls
	FULL_REFRESH_EVERY : UDINT := 60;   // every 60th message carries every tag
END_VAR
VAR
	BrokerUrl : STRING(64) := '192.168.50.240:1883';
	TopicData : STRING(64) := 'raw_data';
	TopicCommands : STRING(64) := 'plc_commands/CONC-BCNF-PLC';
	TopicAcks : STRING(64) := 'plc_acks/CONC-BCNF-PLC';

	MqttLink : MQTT.MQTT_IN_OUT;
	Subscriber : MQTT.MQTTSubscribe;
	Receiver : FB_CommandReceiver;
	Publisher : MQTT.MQTTPublish;
	AckPublisher : MQTT.MQTTPublish;
	IsInitialized : BOOL;
	ConnectedEdge : R_TRIG;

	// Data publishing (PublishData, AppendTag, CommitSent, ForgetMessage)
	PublishTimer : TON;
	IsWaitingForSnapshot : BOOL;
	IsBuilding : BOOL;
	IsMessageReady : BOOL;              // built, waiting for the publisher to be armed
	IsRequested : BOOL;                 // send input of Publisher
	IsPublisherArmed : BOOL := TRUE;    // Publisher has seen send = FALSE since its last message
	IsBuildOk : BOOL;
	IsFullRefresh : BOOL;
	IsForceFullRefresh : BOOL := TRUE;  // the first message, and the next one after a reconnect or overflow
	SlowPublishEdge : R_TRIG;
	SlowPublishCount : UDINT;           // messages that took longer than the library's send time-out
	PublishCount : UDINT;
	NextTag : INT;
	LastTag : INT;
	Index : INT;
	Payload : STRING(32000);            // the generator sizes this from the table's worst-case message
	Used : UDINT;
	TagValue : REAL;
	ValueText : STRING(40);
	// Report-by-exception history: what the bridge last received, committed only after a message went out.
	LastSentValue : ARRAY[1..GVL_Tags.TAG_COUNT] OF REAL;
	LastSentQuality : ARRAY[1..GVL_Tags.TAG_COUNT] OF E_Quality;
	IsInMessage : ARRAY[1..GVL_Tags.TAG_COUNT] OF BOOL;

	// Acknowledgements (PublishAcks)
	Ack : ST_Command;
	AckLine : STRING(40);
	AckPayload : STRING(1000);
	AckUsed : UDINT;
	IsAckBatchReady : BOOL;             // a batch is built and not yet confirmed by the broker
	IsAckRequested : BOOL;
	IsAckPublisherArmed : BOOL := TRUE;
END_VAR
// ---- implementation ----
MqttLink.ClientID := 'CONC-BCNF-PLC';
MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ENABLE := TRUE, URL := BrokerUrl, TIMEOUT := T#10S, TLS := FALSE);
IF NOT IsInitialized THEN
	IsInitialized := TRUE;
	Subscriber.SetMqttInOut(MQTT_IN_OUT := MqttLink);
	Publisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);
	AckPublisher.SetMqttInOut(MQTT_IN_OUT := MqttLink);
END_IF

Subscriber(Subscribe := TRUE, Topic := ADR(TopicCommands), QoSSubscribe := MQTT.QoS.AtLeastOnce,
	ExpectingString := TRUE, Callback := Receiver);
PublishData();
PublishAcks();
