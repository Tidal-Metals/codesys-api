PROGRAM StoreForwardTest
// Store-and-forward test of MQTT.MqttStoreForward (library 1.4.0.0): sequence-numbered samples stamped with the
// PLC's UTC time when captured, on Topic, through the block on PLC_PRG.MqttLink. sfw_test.py drives it.
// Payload, "lines" for Marigraf: _TS:<UTC ms>, sfw_seq:<sequence>, and with PadBytes an sfw_pad line.
// Called by PLC_PRG after the publishers and before the end-of-scan client call; PLC_PRG makes that call when
// IsLiveHandedOff, and CallClient keeps calling while IsSendInFlight, early stop on IsUnsentPending.
VAR
	// Settings, written online
	IsEnabled : BOOL;                       // configures the block once, then pushes every PushPeriod
	IsPushing : BOOL := TRUE;               // FALSE: keep calling the block (drain) without new samples
	PushPeriod : TIME := T#100MS;
	PushesPerTick : UINT := 1;              // samples per tick, a burst within one scan
	PadBytes : UINT := 0;                   // extra payload bytes in an sfw_pad line
	Topic : STRING(64) := 'raw_data/sfw/bench';
	SlotTopicSize : UINT := 64;
	SlotPayloadSize : UDINT := 2048;
	LiveLanes : UINT := 2;
	BacklogLanes : UINT := 4;
	StorageBytes : UDINT := 262144;         // part of Storage given to Configure (a small value tests overflow)
	ConfigureRequest : BOOL;                // Reset(Discard) and Configure again with the settings above
	CheckRequest : BOOL;                    // CheckOwnership once
	IsCheckEveryScan : BOOL;                // CheckOwnership in every scan (costs a walk of every slot)
	ResetStats : BOOL;
	// the block's runtime inputs, passed every call
	Enable : BOOL := TRUE;
	AcceptPush : BOOL := TRUE;
	IsHoldOnNoSubscribers : BOOL := TRUE;
	NoSubscriberPause : TIME := T#5S;
	BacklogStartsPerCall : UINT := 2;
	BacklogBytesPerCall : UDINT := 8192;
	ReservedOutSlots : UINT := 2;
	ReservedCredits : UINT := 2;
	IsInferRefusals : BOOL;

	Telemetry : MQTT.MqttStoreForward;
	Storage : ARRAY[0..262143] OF BYTE;       // 256 KiB, keeps the application small (RealisticSfwTest has the big buffer)
	Payload : STRING(32767);
	IsPushDue : BOOL;
	NowPushUs : ULINT;
	NextPushUs : ULINT;
	PeriodUs : ULINT;
	StampMs : ULINT;
	LastStampMs : ULINT;
	Used : UDINT;
	pPayload : POINTER TO BYTE;
	PadIndex : UINT;
	Burst : UINT;
	StartUs : ULINT;

	// Results, read online
	IsConfigured : BOOL;
	ConfigureCount : UDINT;
	NextSequence : UDINT;                   // the sequence of the next sample (the first is 1)
	PushFailCount : UDINT;
	CheckCount : UDINT;
	CheckFailCount : UDINT;
	PushUs : UDINT;
	MaxPushUs : UDINT;
	BlockUs : UDINT;
	MaxBlockUs : UDINT;
	IsSendInFlight : BOOL;                  // PLC_PRG.CallClient keeps calling the client while this is TRUE
	IsLiveHandedOff : BOOL;                 // PLC_PRG makes the end-of-scan client call
	LiveHandOffScans : UDINT;
END_VAR
// ---- implementation ----
IF ResetStats THEN
	ResetStats := FALSE;
	PushFailCount := 0; CheckCount := 0; CheckFailCount := 0; MaxPushUs := 0; MaxBlockUs := 0; LiveHandOffScans := 0;
END_IF
IF ConfigureRequest OR (IsEnabled AND NOT IsConfigured) THEN
	ConfigureRequest := FALSE;
	Telemetry.Reset(Discard := TRUE);
	Telemetry.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	IsConfigured := Telemetry.Configure(Storage := ADR(Storage), StorageSize := MIN(StorageBytes, SIZEOF(Storage)),
		SlotTopicSize := SlotTopicSize, SlotPayloadSize := SlotPayloadSize, LiveLanes := LiveLanes,
		BacklogLanes := BacklogLanes);
	ConfigureCount := ConfigureCount + 1;
	IF NextSequence = 0 THEN
		NextSequence := 1;
	END_IF
END_IF

// a fixed schedule (a TON restarted on its Q runs a scan or two slow per period); resynchronised after a pause
IsPushDue := FALSE;
IF IsEnabled AND IsPushing THEN
	NowPushUs := NowUs();
	PeriodUs := TIME_TO_ULINT(PushPeriod) * 1000;
	IF NextPushUs = 0 OR NowPushUs > NextPushUs + PeriodUs THEN
		NextPushUs := NowPushUs;
	END_IF
	IF NowPushUs >= NextPushUs THEN
		IsPushDue := TRUE;
		NextPushUs := NextPushUs + PeriodUs;
	END_IF
ELSE
	NextPushUs := 0;
END_IF
IF IsPushDue THEN
	FOR Burst := 1 TO MAX(PushesPerTick, 1) DO
		StartUs := NowUs();
		// the capture time, unique per sample so Marigraf keeps every one
		SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := StampMs);
		IF StampMs <= LastStampMs THEN
			StampMs := LastStampMs + 1;
		END_IF
		LastStampMs := StampMs;
		Used := 0;
		AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := CONCAT('_TS:', ULINT_TO_STRING(StampMs)), Used := Used);
		AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := CONCAT('$Lsfw_seq:', UDINT_TO_STRING(NextSequence)), Used := Used);
		IF PadBytes > 0 THEN
			AppendText(pBuffer := ADR(Payload), Capacity := SIZEOF(Payload), Text := '$Lsfw_pad:', Used := Used);
			pPayload := ADR(Payload);
			FOR PadIndex := 1 TO PadBytes DO
				IF Used + 1 < SIZEOF(Payload) THEN
					pPayload[Used] := 16#30;	// '0'
					Used := Used + 1;
				END_IF
			END_FOR
			pPayload[Used] := 0;
		END_IF
		IF Telemetry.Push(Topic := ADR(Topic), Payload := ADR(Payload), Length := Used) THEN
			NextSequence := NextSequence + 1;
		ELSE
			PushFailCount := PushFailCount + 1;
		END_IF
		PushUs := ULINT_TO_UDINT(NowUs() - StartUs);
		MaxPushUs := MAX(MaxPushUs, PushUs);
	END_FOR
END_IF

StartUs := NowUs();
Telemetry(AcceptPush := AcceptPush, Enable := Enable, IsHoldOnNoSubscribers := IsHoldOnNoSubscribers,
	NoSubscriberPause := NoSubscriberPause, BacklogStartsPerCall := BacklogStartsPerCall,
	BacklogBytesPerCall := BacklogBytesPerCall, ReservedOutSlots := ReservedOutSlots, ReservedCredits := ReservedCredits,
	IsInferRefusals := IsInferRefusals);
BlockUs := ULINT_TO_UDINT(NowUs() - StartUs);
MaxBlockUs := MAX(MaxBlockUs, BlockUs);

IF CheckRequest OR IsCheckEveryScan THEN
	CheckRequest := FALSE;
	CheckCount := CheckCount + 1;
	IF NOT Telemetry.CheckOwnership() THEN
		CheckFailCount := CheckFailCount + 1;
	END_IF
END_IF
IsSendInFlight := Telemetry.InFlightCount > 0;
IsLiveHandedOff := Telemetry.IsLiveHandedOff;
IF IsLiveHandedOff THEN
	LiveHandOffScans := LiveHandOffScans + 1;
END_IF
