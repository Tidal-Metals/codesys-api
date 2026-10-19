// Action PublishData: once a second, ask the control task for a snapshot, build the message from it over
// several calls (changed tags only, plus a full refresh now and then), and publish it as one message.
// ---- implementation ----
ConnectedEdge(CLK := MqttLink.BROKER_CONNECTED);
IF ConnectedEdge.Q THEN
	IsForceFullRefresh := TRUE;         // the bridge may have missed messages while we were away
END_IF

PublishTimer(IN := NOT PublishTimer.Q, PT := T#1S);
IF PublishTimer.Q AND MqttLink.BROKER_CONNECTED
		AND NOT (IsWaitingForSnapshot OR IsBuilding OR IsMessageReady OR IsRequested) THEN
	GVL_Tags.SnapshotRequest := GVL_Tags.SnapshotRequest + 1;
	IsWaitingForSnapshot := TRUE;
END_IF

IF IsWaitingForSnapshot AND GVL_Tags.SnapshotSequence = GVL_Tags.SnapshotRequest THEN
	IsWaitingForSnapshot := FALSE;
	PublishCount := PublishCount + 1;
	IsFullRefresh := IsForceFullRefresh OR (PublishCount MOD FULL_REFRESH_EVERY) = 1;
	IsForceFullRefresh := FALSE;        // set again by a reconnect or a message that didn't fit
	Used := 0;
	Payload := '';
	IsBuildOk := TRUE;
	NextTag := 1;
	IsBuilding := TRUE;
END_IF

IF IsBuilding THEN
	LastTag := MIN(GVL_Tags.TAG_COUNT, NextTag + TAGS_PER_CALL - 1);
	FOR Index := NextTag TO LastTag DO
		AppendTag();
	END_FOR
	NextTag := LastTag + 1;
	IF NextTag > GVL_Tags.TAG_COUNT THEN
		IsBuilding := FALSE;
		IF NOT IsBuildOk THEN
			ForgetMessage();            // didn't fit: send nothing, try a full message next time
		ELSE
			IsMessageReady := Used > 0; // nothing changed: nothing to send
		END_IF
	END_IF
END_IF

// MQTTPublish starts on a rising edge of send, so it must see FALSE between two messages. Once started, the
// library keeps the request until the broker has it (it resends after a reconnect) and reads Payload through
// its pointer the whole time, so Payload, the snapshot and IsInMessage stay untouched until done.
// SendTimeout only says it is taking long: it does not end the request.
IF IsMessageReady AND NOT IsRequested AND IsPublisherArmed THEN
	IsRequested := TRUE;
END_IF
Publisher(Topic := ADR(TopicData), PayloadString := ADR(Payload), PublishAsString := TRUE,
	QoSIn := MQTT.QoS.AtMostOnce, MRetain := FALSE, send := IsRequested);
IsPublisherArmed := NOT IsRequested;
IF Publisher.done THEN
	IsRequested := FALSE;
	IsMessageReady := FALSE;
	CommitSent();                       // only now does the history move on
END_IF
SlowPublishEdge(CLK := Publisher.SendTimeout);
IF SlowPublishEdge.Q THEN
	SlowPublishCount := SlowPublishCount + 1;
END_IF
