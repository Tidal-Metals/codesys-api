FUNCTION_BLOCK BenchFirstSubscription
// BCNF's FirstSubscription (PLC_BCNF_4_16_26) verbatim, on BcnfComms.MQTT_SUBSCRIBE and bench topics:
// plc_commands/CONC-BCNF-PLC -> raw_data_demo/bcnf/commands, plc_status/CONC -> raw_data_demo/bcnf/status.
VAR_INPUT
END_VAR
VAR_OUTPUT
END_VAR
VAR
	// ===== MQTT SUBSCRIPTION COMPONENTS =====
	collector: MQTT.CallbackCollector;          // Manages multiple callback receivers
	SUB1: MQTT.MQTTSubscribe;                   // Main MQTT subscription function block
	receiver: MQTT.ReceiveString;               // String message receiver/parser

	// ===== READY STATE SUBSCRIPTION =====
	collectorReady: MQTT.CallbackCollector;     // Callback collector for ready messages
	SUB2: MQTT.MQTTSubscribe;                   // Ready state subscription function block
	receiverReady: MQTT.ReceiveString;          // Ready state message receiver/parser

	// ===== INITIALIZATION =====
	init: BOOL;
END_VAR
// ---- implementation ----
// ===== ONE-TIME INITIALIZATION =====
IF NOT init THEN
	init := TRUE;

	SUB1.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_SUBSCRIBE);
	collector.put(instance := receiver);
	receiver.initAsFindTopic(
		compString := ADR('raw_data_demo/bcnf/commands'),
		returnHit := TRUE
	);

	SUB2.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_SUBSCRIBE);
	collectorReady.put(instance := receiverReady);
	receiverReady.initAsFindTopic(
		compString := ADR('raw_data_demo/bcnf/status'),
		returnHit := TRUE
	);

END_IF;

// ===== ACTIVE SUBSCRIPTION =====
SUB1(
	Subscribe := TRUE,
	Topic := ADR('raw_data_demo/bcnf/commands'),
	QoSSubscribe := MQTT.QoS.ExactlyOnce,
	ExpectingString := TRUE,
	Callback := collector
);

SUB2(
	Subscribe := TRUE,
	Topic := ADR('raw_data_demo/bcnf/status'),
	QoSSubscribe := MQTT.QoS.ExactlyOnce,
	ExpectingString := TRUE,
	Callback := collectorReady
);
