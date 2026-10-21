FUNCTION_BLOCK FB_EdgeReceiver IMPLEMENTS MQTT.MQTT_SUBSCRIBE_CALLBACK
// Subscription callback for EdgeTest: the size and Adler-32 of the last message, and how many arrived.
// ReceivedCount changes last, so a reader that sees a new count also sees that message's size and sum.
VAR_OUTPUT
	ReceivedCount : UDINT;
	LastSize : UDINT;
	LastAdler32 : UDINT;
	// Messages starting with 8 ASCII digits carry a sequence number (qos_test.py); write ResetSequence online
	LastSequence : UDINT;
	InOrderCount : UDINT;               // sequence = previous + 1
	DuplicateCount : UDINT;             // sequence <= previous: delivered again
	GapCount : UDINT;                   // sequence numbers skipped: lost
END_VAR
VAR_INPUT
	ResetSequence : BOOL;               // written online; cleared by the next message
END_VAR
// ---- implementation ----
