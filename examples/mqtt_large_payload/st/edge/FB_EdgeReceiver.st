FUNCTION_BLOCK FB_EdgeReceiver IMPLEMENTS MQTT.MQTT_SUBSCRIBE_CALLBACK
// Subscription callback for EdgeTest: the size and Adler-32 of the last message, and how many arrived.
// ReceivedCount changes last, so a reader that sees a new count also sees that message's size and sum.
VAR_OUTPUT
	ReceivedCount : UDINT;
	LastSize : UDINT;
	LastAdler32 : UDINT;
END_VAR
// ---- implementation ----
