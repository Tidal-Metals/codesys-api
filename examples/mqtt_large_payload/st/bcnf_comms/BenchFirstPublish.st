FUNCTION_BLOCK BenchFirstPublish
// BCNF's FirstPublish (PLC_BCNF_4_16_26) verbatim, on BcnfComms.MQTT_PUBLISH; topic raw_data -> raw_data_demo/bcnf/raw;
// SysTimeRtcHighResGet -> NowUs() (the demo has no SysTimeRtc reference; the value is not published).
VAR_INPUT
    InterlockData1: STRING(255);
    InterlockData2: STRING(255);
    InterlockData3: STRING(255);
    InterlockData4: STRING(255);
    InterlockData5: STRING(255);
    InterlockData6: STRING(255);
    InterlockData7: STRING(255);
END_VAR
VAR_OUTPUT
    PublishDone: BOOL;                          // Indicates when publish operation completes
END_VAR
VAR
    // ===== MQTT PUBLISHER CORE =====
    publisher1: MQTT.MQTTPublish;
    publisher2: MQTT.MQTTPublish;
    publisher3: MQTT.MQTTPublish;
    publisher4: MQTT.MQTTPublish;
    publisher5: MQTT.MQTTPublish;
    publisher6: MQTT.MQTTPublish;
    publisher7: MQTT.MQTTPublish;

    init: BOOL;                                // One-time initialization flag

    // ===== MESSAGE CONTENT =====
    fullPayload1: STRING(255);
    fullPayload2: STRING(255);
    fullPayload3: STRING(255);
    fullPayload4: STRING(255);
    fullPayload5: STRING(255);
    fullPayload6: STRING(255);
    fullPayload7: STRING(255);

    // ===== PUBLISHING CONTROL =====
    sendTimer: TON;                            // Timer controlling publish frequency
    readyToSend: BOOL;                         // Flag indicating ready to publish

    // ===== MESSAGE STATISTICS =====
    TicCount: UDINT;
    TicCountOld: UDINT;
    TicsPerSecond: REAL;
    totalMessages: UDINT;
    PulseCount: UDINT;
    previousTotalMessages: UDINT;
    messagesPerSecond: REAL;

    // ===== TIMING AND STATE TRACKING =====
    publisher_done_prev: BOOL;
    rateTimer: TON;

    // ===== TIMESTAMP GENERATION =====
    dtNowString: STRING;
    RTC: ULINT;

    Pulse: BOOL;
END_VAR
// ---- implementation ----
// ===== EXPOSE PUBLISH STATE =====
TicCount := TicCount + 1;
PublishDone := publisher1.done;

// ===== ONE-TIME INITIALIZATION =====
IF NOT init THEN
    init := TRUE;
    publisher1.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher2.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher3.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher4.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher5.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher6.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
    publisher7.SetMqttInOut(MQTT_IN_OUT := BcnfComms.MQTT_PUBLISH);
END_IF

// ===== PUBLISH TIMING CONTROL =====
sendTimer(IN := NOT sendTimer.Q, PT := T#1000MS);

// ===== MESSAGE PREPARATION =====
IF sendTimer.Q AND NOT readyToSend THEN
    readyToSend := TRUE;
    PulseCount := PulseCount + 1;
    IF Pulse = TRUE THEN
        Pulse := FALSE;
    ELSE
        Pulse := TRUE;
    END_IF
    RTC := NowUs();
    dtNowString := TO_STRING(RTC);

    fullPayload1 := InterlockData1;
    fullPayload2 := InterlockData2;
    fullPayload3 := InterlockData3;
    fullPayload4 := InterlockData4;
    fullPayload5 := InterlockData5;
    fullPayload6 := InterlockData6;
    fullPayload7 := InterlockData7;

    IF LEN(fullPayload1) = 0 THEN
        readyToSend := FALSE;
    END_IF;
END_IF;

// ===== PUBLISH COMPLETION TRACKING =====
IF (publisher1.done OR LEN(fullPayload1) = 0) AND
   (publisher2.done OR LEN(fullPayload2) = 0) AND
   (publisher3.done OR LEN(fullPayload3) = 0) AND
   (publisher4.done OR LEN(fullPayload4) = 0) AND
   (publisher5.done OR LEN(fullPayload5) = 0) AND
   (publisher6.done OR LEN(fullPayload6) = 0) AND
   (publisher7.done OR LEN(fullPayload7) = 0) THEN
    IF NOT publisher_done_prev THEN
        totalMessages := totalMessages + 1;
    END_IF;
    PublishDone := TRUE;
ELSE
    PublishDone := FALSE;
END_IF;

publisher_done_prev := PublishDone;

// ===== PUBLISH STATE RESET =====
IF PublishDone THEN
    readyToSend := FALSE;
END_IF;

// ===== PUBLISHING RATE MONITORING =====
rateTimer(IN := NOT rateTimer.Q, PT := T#500MS);
IF rateTimer.Q THEN
    messagesPerSecond := TO_REAL(totalMessages - previousTotalMessages) / 2.0;
    previousTotalMessages := totalMessages;
    TicsPerSecond := TO_REAL(TicCount - TicCountOld) / 2.0;
    TicCountOld := TicCount;
END_IF;

// ===== MQTT PUBLISH OPERATION =====
publisher1(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload1),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload1) > 0));

publisher2(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload2),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload2) > 0));

publisher3(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload3),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload3) > 0));

publisher4(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload4),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload4) > 0));

publisher5(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload5),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload5) > 0));

publisher6(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload6),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload6) > 0));

publisher7(
    Topic := ADR('raw_data_demo/bcnf/raw'),
    PayloadString := ADR(fullPayload7),
    PublishAsString := TRUE,
    QoSin := MQTT.QoS.AtMostOnce,
    MRetain := FALSE,
    send := readyToSend AND (LEN(fullPayload7) > 0));


// ------------------------- //
// ------------------------- //
// ------------------------- //
// ------------------------- //
// ------------------------- //

