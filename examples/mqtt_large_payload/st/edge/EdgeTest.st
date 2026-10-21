PROGRAM EdgeTest
// Edge-case test for the MQTT library, driven online by edge_test.py; idle unless IsEnabled.
// Send: when SendSequence changes, publishes SendSize payload bytes on TopicOut. Byte i is
// (i * 31 + SendSequence) MOD 251, so the broker-side checker can verify every byte of every size.
// Receive: every message on TopicIn is counted with its size and Adler-32 (Receiver).
VAR
	IsEnabled : BOOL;                   // written online
	SendSize : UDINT := 100;            // written online: payload bytes of the next message
	IsQos1 : BOOL;                      // written online
	SendSequence : UDINT;               // written online; a new value starts a send
	DoneSequence : UDINT;               // the sequence of the last message the library reported done
	TimeoutCount : UDINT;               // rising edges of Publisher.SendTimeout
	IsEchoEnabled : BOOL;               // written online: answer every received message on TopicEcho (QoS 1)
	EchoCount : UDINT;                  // echoes the library reported done
	Receiver : FB_EdgeReceiver;
	TopicEcho : STRING(64) := 'raw_data_demo/edge_echo';
	EchoText : STRING(32);
	EchoPublisher : MQTT.MQTTPublish;
	IsEchoRequested : BOOL;
	IsEchoArmed : BOOL := TRUE;
	EchoedCount : UDINT;                // Receiver.ReceivedCount at the last echo started
	TopicOut : STRING(64) := 'raw_data_demo/edge';
	TopicIn : STRING(64) := 'raw_data_demo/edge_in';
	Publisher : MQTT.MQTTPublish;
	Subscriber : MQTT.MQTTSubscribe;
	IsReady : BOOL;
	IsRequested : BOOL;
	IsArmed : BOOL := TRUE;
	StartedSequence : UDINT;
	PublishQoS : MQTT.QoS;
	TimeoutEdge : R_TRIG;
	Payload : ARRAY[0..MAX_PAYLOAD - 1] OF BYTE;
	Index : UDINT;
END_VAR
VAR CONSTANT
	MAX_PAYLOAD : UDINT := 40000;
END_VAR
// ---- implementation ----
IF NOT IsReady THEN
	IsReady := TRUE;
	Publisher.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	Subscriber.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	EchoPublisher.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
END_IF

Subscriber(Subscribe := IsEnabled, Topic := ADR(TopicIn), QoSSubscribe := MQTT.QoS.AtLeastOnce,
	ExpectingString := FALSE, Callback := Receiver);

// MQTTPublish starts on a rising edge of send: a new request only once the publisher has been called with
// send FALSE after the previous done (IsArmed). Without it a request written in the scan after done is lost.
IF IsEnabled AND NOT IsRequested AND IsArmed AND SendSequence <> StartedSequence AND SendSize > 0 AND SendSize <= MAX_PAYLOAD THEN
	FOR Index := 0 TO SendSize - 1 DO
		Payload[Index] := UDINT_TO_BYTE((Index * 31 + SendSequence) MOD 251);
	END_FOR
	StartedSequence := SendSequence;
	IsRequested := TRUE;
	IsArmed := FALSE;
END_IF
IF IsQos1 THEN
	PublishQoS := MQTT.QoS.AtLeastOnce;
ELSE
	PublishQoS := MQTT.QoS.AtMostOnce;
END_IF
Publisher(Topic := ADR(TopicOut), PublishAsString := FALSE, Payload := ADR(Payload), PayloadLength := SendSize,
	QoSIn := PublishQoS, MRetain := FALSE, send := IsRequested);
IF NOT IsRequested THEN
	IsArmed := TRUE;	// the publisher has seen send FALSE
END_IF
IF Publisher.done THEN
	IsRequested := FALSE;
	DoneSequence := StartedSequence;
END_IF
TimeoutEdge(CLK := Publisher.SendTimeout);
IF TimeoutEdge.Q THEN
	TimeoutCount := TimeoutCount + 1;
END_IF

// Echo (command and acknowledgement round trip): answer the newest received message with its count, QoS 1,
// like PRG_Comms acknowledging a command. Same armed rule as above.
IF IsEchoEnabled AND NOT IsEchoRequested AND IsEchoArmed AND Receiver.ReceivedCount <> EchoedCount THEN
	EchoedCount := Receiver.ReceivedCount;
	EchoText := UDINT_TO_STRING(EchoedCount);
	IsEchoRequested := TRUE;
	IsEchoArmed := FALSE;
END_IF
EchoPublisher(Topic := ADR(TopicEcho), PayloadString := ADR(EchoText), PublishAsString := TRUE,
	QoSIn := MQTT.QoS.AtLeastOnce, MRetain := FALSE, send := IsEchoRequested);
IF NOT IsEchoRequested THEN
	IsEchoArmed := TRUE;
END_IF
IF EchoPublisher.done THEN
	IsEchoRequested := FALSE;
	EchoCount := EchoCount + 1;
END_IF
