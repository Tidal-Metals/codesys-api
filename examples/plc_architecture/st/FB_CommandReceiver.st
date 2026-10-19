FUNCTION_BLOCK FB_CommandReceiver IMPLEMENTS MQTT.MQTT_SUBSCRIBE_CALLBACK
// MQTT subscription callback: turns every received command into an ST_Command and queues it for the
// control task, instead of keeping only the latest message. Runs in the comms task (inside the MQTT client).
// Message format: <id>,<tag>=<value>,<sent_ms>   e.g. '1042,P-1502=1,1769612037947'
VAR_OUTPUT
	ReceivedCount : UDINT;
	MalformedCount : UDINT;
	DroppedCount : UDINT;               // queue full: no acknowledgement, so the sender retries
END_VAR
VAR
	Line : STRING(255);
END_VAR
// ---- implementation ----
// Everything happens in PublishReceived, called by the MQTT library for each message.
