// Action PublishAcks: answer commands as "<id>:<result>" lines, several per message. A batch stays until
// the broker confirms it (QoS 1); the library resends it after a reconnect, so an answer is never dropped here.
// ---- implementation ----
IF NOT IsAckBatchReady AND MqttLink.BROKER_CONNECTED THEN
	AckUsed := 0;
	AckPayload := '';
	WHILE AckUsed < 900 AND_THEN GVL_Tags.Acks.Pop(Item := Ack) DO
		AckLine := CONCAT(CONCAT(UDINT_TO_STRING(Ack.Id), ':'), USINT_TO_STRING(TO_USINT(Ack.Result)));
		AppendZ(pBuffer := ADR(AckPayload), Capacity := SIZEOF(AckPayload), pText := ADR(AckLine), Used := AckUsed);
		AppendZ(pBuffer := ADR(AckPayload), Capacity := SIZEOF(AckPayload), pText := ADR('$N'), Used := AckUsed);
	END_WHILE
	IsAckBatchReady := AckUsed > 0;
END_IF

// Same publisher rules as PublishData: re-arm between sends, keep the batch until done.
IF IsAckBatchReady AND NOT IsAckRequested AND IsAckPublisherArmed THEN
	IsAckRequested := TRUE;
END_IF
AckPublisher(Topic := ADR(TopicAcks), PayloadString := ADR(AckPayload), PublishAsString := TRUE,
	QoSIn := MQTT.QoS.AtLeastOnce, MRetain := FALSE, send := IsAckRequested);
IsAckPublisherArmed := NOT IsAckRequested;
IF AckPublisher.done THEN
	IsAckRequested := FALSE;
	IsAckBatchReady := FALSE;           // confirmed: the next batch can be built
END_IF
