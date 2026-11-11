PROGRAM RealisticSfwTest
// A realistic two-stream outage load through MQTT.MqttStoreForward (library 1.4.0.0, or the adaptive version with the
// same Configure): Slow pushes one ~SlowBytes sample per SlowPeriod on SlowTopic, Fast one ~FastBytes sample per
// FastPeriod on FastTopic, each stamped with the PLC's UTC time when captured. sfw_test.py realistic drives it.
// Payload, "lines" for Marigraf: _TS:<UTC ms>, sfw_slow_seq:<n> or sfw_fast_seq:<n>, then p:000... padding lines of at
// most PAD_LINE_CHARS characters (Marigraf drops lines over 4,096 bytes) up to the target size (BuildPayload).
// IsTwoBlocks: BlockSlow and BlockFast, each with its own slot size and its share of Storage (StorageShareSlowPercent);
// FALSE: BlockSlow takes both streams over all of StorageBytes, its slots sized for the larger sample. The mode is
// latched by the configuration (IsTwoBlocksConfigured); change it with ConfigureRequest.
// Called by PLC_PRG after MixedPushTest, before the end-of-scan client call; PLC_PRG makes that call when
// IsLiveHandedOff, and CallClient keeps calling while IsSendInFlight, early stop on IsUnsentPending while IsEnabled
// (patch_demo_store_forward.py adds all three, in the MQTT 5 demo copy only).
VAR CONSTANT
	PAD_LINE_CHARS : UDINT := 100;          // a padding line "p:000...", line feed not counted
	SLOT_ROUND_BYTES : UDINT := 1024;       // a slot size of 0 is the sample size rounded up to this
	STORAGE_ALIGN : UDINT := 8;             // BlockFast's share starts on this boundary
END_VAR
VAR
	// Settings, written online
	IsEnabled : BOOL;                       // configures on the first enable, then pushes both streams
	IsPushing : BOOL := TRUE;               // FALSE: keep calling the blocks (drain) without new samples
	SlowPeriod : TIME := T#1S;
	SlowBytes : UDINT := 26000;             // payload size, about (padding lines stop within 3 bytes of it)
	SlowTopic : STRING(64) := 'raw_data/sfw/slow';
	FastPeriod : TIME := T#100MS;
	FastBytes : UDINT := 5000;
	FastTopic : STRING(64) := 'raw_data/sfw/fast';
	ResetStats : BOOL;
	// the configuration: on the first enable and on ConfigureRequest (Reset(Discard) first; Reset and Configure refuse
	// while a sample is in the client, and the configuration is then retried every scan while IsEnabled)
	IsTwoBlocks : BOOL := TRUE;
	StorageBytes : UDINT := 2621440;        // part of Storage given to the block(s)
	StorageShareSlowPercent : UDINT := 33;  // two blocks: BlockSlow's share of StorageBytes, BlockFast has the rest
	SlotTopicSize : UINT := 64;
	SlowSlotPayloadSize : UDINT := 0;       // 0: SlowBytes rounded up to SLOT_ROUND_BYTES
	FastSlotPayloadSize : UDINT := 0;       // 0: FastBytes rounded up; one block: the larger of the two slot sizes
	SlowLiveLanes : UINT := 1;              // two blocks
	SlowBacklogLanes : UINT := 2;
	FastLiveLanes : UINT := 1;
	FastBacklogLanes : UINT := 2;
	OneBlockLiveLanes : UINT := 2;          // one block
	OneBlockBacklogLanes : UINT := 4;
	ConfigureRequest : BOOL;                // Reset(Discard) and Configure again with the settings above
	// the blocks' runtime inputs, passed to both every call
	BacklogStartsPerCall : UINT := 3;
	BacklogBytesPerCall : UDINT := 16383;
	ReservedOutSlots : UINT := 2;
	ReservedCredits : UINT := 2;
	IsHoldOnNoSubscribers : BOOL := TRUE;
	NoSubscriberPause : TIME := T#5S;

	BlockSlow : MQTT.MqttStoreForward;
	BlockFast : MQTT.MqttStoreForward;      // idle (not configured) with one block
	Storage : ARRAY[0..2621439] OF BYTE;      // 2.5 MiB, one array for both blocks (the P2CDS-622 refused larger buffers)
	Payload : STRING(32767);
	pStorage : POINTER TO BYTE;
	TotalBytes : UDINT;
	IsSlowConfigured : BOOL;
	IsFastConfigured : BOOL;
	IsSlowDue : BOOL;
	IsFastDue : BOOL;
	NowPushUs : ULINT;
	PeriodUs : ULINT;
	NextSlowUs : ULINT;
	NextFastUs : ULINT;
	StampMs : ULINT;
	LastSlowStampMs : ULINT;
	LastFastStampMs : ULINT;
	IsPushed : BOOL;
	StartUs : ULINT;
	// BuildPayload's inputs and work
	BuildStampMs : ULINT;
	BuildSeqKey : STRING(16);               // 'sfw_slow_seq:' or 'sfw_fast_seq:'
	BuildSeq : UDINT;
	BuildTargetBytes : UDINT;
	Used : UDINT;                           // BuildPayload's result: the payload's length
	pPayload : POINTER TO BYTE;
	PayloadLimit : UDINT;
	LineChars : UDINT;
	PadIndex : UDINT;

	// Results, read online (the blocks' own outputs: BlockSlow.<output>, BlockFast.<output>)
	IsConfigured : BOOL;
	IsTwoBlocksConfigured : BOOL;
	ConfigureCount : UDINT;
	SlowSlotBytes : UDINT;                  // the configured slot payload sizes and storage shares
	FastSlotBytes : UDINT;
	SlowStorageBytes : UDINT;
	FastStorageBytes : UDINT;
	LastSlowConfigureError : MQTT.STORE_FORWARD_ERROR;
	LastFastConfigureError : MQTT.STORE_FORWARD_ERROR;
	SlowNextSeq : UDINT;                    // the sequence of the next sample (the first is 1)
	FastNextSeq : UDINT;
	SlowPushFailCount : UDINT;
	FastPushFailCount : UDINT;
	SlowSkippedCount : UDINT;               // periods skipped by a resynchronisation (a scan more than a period late)
	FastSkippedCount : UDINT;
	SlowPushUs : UDINT;                     // building the payload and the Push
	MaxSlowPushUs : UDINT;
	FastPushUs : UDINT;
	MaxFastPushUs : UDINT;
	SlowBlockUs : UDINT;                    // the block's call, every scan
	MaxSlowBlockUs : UDINT;
	FastBlockUs : UDINT;
	MaxFastBlockUs : UDINT;
	HasWork : BOOL;                         // either block holds a sample
	IsSendInFlight : BOOL;                  // PLC_PRG.CallClient keeps calling the client while this is TRUE
	IsLiveHandedOff : BOOL;                 // PLC_PRG makes the end-of-scan client call
	LiveHandOffScans : UDINT;
END_VAR
// ---- implementation ----
IF ResetStats THEN
	ResetStats := FALSE;
	SlowPushFailCount := 0; FastPushFailCount := 0; SlowSkippedCount := 0; FastSkippedCount := 0;
	MaxSlowPushUs := 0; MaxFastPushUs := 0; MaxSlowBlockUs := 0; MaxFastBlockUs := 0; LiveHandOffScans := 0;
END_IF

// Configure before the first push (after SetMqttInOut: Configure reads COM_CONFIG.CountSlotsOut)
IF ConfigureRequest OR (IsEnabled AND NOT IsConfigured) THEN
	ConfigureRequest := FALSE;
	IsTwoBlocksConfigured := IsTwoBlocks;
	TotalBytes := MIN(StorageBytes, SIZEOF(Storage));
	SlowSlotBytes := SlowSlotPayloadSize;
	IF SlowSlotBytes = 0 THEN
		SlowSlotBytes := (SlowBytes + SLOT_ROUND_BYTES - 1) / SLOT_ROUND_BYTES * SLOT_ROUND_BYTES;
	END_IF
	FastSlotBytes := FastSlotPayloadSize;
	IF FastSlotBytes = 0 THEN
		FastSlotBytes := (FastBytes + SLOT_ROUND_BYTES - 1) / SLOT_ROUND_BYTES * SLOT_ROUND_BYTES;
	END_IF
	IF IsTwoBlocksConfigured THEN
		SlowStorageBytes := TotalBytes * MIN(StorageShareSlowPercent, 100) / 100 / STORAGE_ALIGN * STORAGE_ALIGN;
		FastStorageBytes := TotalBytes - SlowStorageBytes;
	ELSE
		SlowSlotBytes := MAX(SlowSlotBytes, FastSlotBytes);
		FastSlotBytes := 0;
		SlowStorageBytes := TotalBytes;
		FastStorageBytes := 0;
	END_IF
	BlockSlow.Reset(Discard := TRUE);
	BlockFast.Reset(Discard := TRUE);
	BlockSlow.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	BlockFast.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	pStorage := ADR(Storage);
	IF IsTwoBlocksConfigured THEN
		IsSlowConfigured := BlockSlow.Configure(Storage := pStorage, StorageSize := SlowStorageBytes,
			SlotTopicSize := SlotTopicSize, SlotPayloadSize := SlowSlotBytes, LiveLanes := SlowLiveLanes,
			BacklogLanes := SlowBacklogLanes);
		IsFastConfigured := BlockFast.Configure(Storage := pStorage + SlowStorageBytes, StorageSize := FastStorageBytes,
			SlotTopicSize := SlotTopicSize, SlotPayloadSize := FastSlotBytes, LiveLanes := FastLiveLanes,
			BacklogLanes := FastBacklogLanes);
	ELSE
		IsSlowConfigured := BlockSlow.Configure(Storage := pStorage, StorageSize := SlowStorageBytes,
			SlotTopicSize := SlotTopicSize, SlotPayloadSize := SlowSlotBytes, LiveLanes := OneBlockLiveLanes,
			BacklogLanes := OneBlockBacklogLanes);
		IsFastConfigured := TRUE;
	END_IF
	IsConfigured := IsSlowConfigured AND IsFastConfigured;
	ConfigureCount := ConfigureCount + 1;
	LastSlowConfigureError := BlockSlow.LastConfigureError;
	LastFastConfigureError := BlockFast.LastConfigureError;
	IF SlowNextSeq = 0 THEN
		SlowNextSeq := 1;
	END_IF
	IF FastNextSeq = 0 THEN
		FastNextSeq := 1;
	END_IF
END_IF

// fixed schedules (a TON restarted on its Q runs a scan or two slow per period); resynchronised after a pause
IsSlowDue := FALSE;
IsFastDue := FALSE;
IF IsEnabled AND IsPushing THEN
	NowPushUs := NowUs();
	PeriodUs := MAX(TIME_TO_ULINT(SlowPeriod), 1) * 1000;
	IF NextSlowUs = 0 OR NowPushUs > NextSlowUs + PeriodUs THEN
		IF NextSlowUs <> 0 THEN
			SlowSkippedCount := SlowSkippedCount + ULINT_TO_UDINT((NowPushUs - NextSlowUs) / PeriodUs);
		END_IF
		NextSlowUs := NowPushUs;
	END_IF
	IF NowPushUs >= NextSlowUs THEN
		IsSlowDue := TRUE;
		NextSlowUs := NextSlowUs + PeriodUs;
	END_IF
	PeriodUs := MAX(TIME_TO_ULINT(FastPeriod), 1) * 1000;
	IF NextFastUs = 0 OR NowPushUs > NextFastUs + PeriodUs THEN
		IF NextFastUs <> 0 THEN
			FastSkippedCount := FastSkippedCount + ULINT_TO_UDINT((NowPushUs - NextFastUs) / PeriodUs);
		END_IF
		NextFastUs := NowPushUs;
	END_IF
	IF NowPushUs >= NextFastUs THEN
		IsFastDue := TRUE;
		NextFastUs := NextFastUs + PeriodUs;
	END_IF
ELSE
	NextSlowUs := 0;
	NextFastUs := 0;
END_IF

IF IsSlowDue THEN
	StartUs := NowUs();
	// the capture time, unique and increasing per stream so Marigraf keeps every sample
	SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := StampMs);
	IF StampMs <= LastSlowStampMs THEN
		StampMs := LastSlowStampMs + 1;
	END_IF
	LastSlowStampMs := StampMs;
	BuildStampMs := StampMs;
	BuildSeqKey := 'sfw_slow_seq:';
	BuildSeq := SlowNextSeq;
	BuildTargetBytes := SlowBytes;
	BuildPayload();
	IsPushed := BlockSlow.Push(Topic := ADR(SlowTopic), Payload := ADR(Payload), Length := Used);
	IF IsPushed THEN
		SlowNextSeq := SlowNextSeq + 1;
	ELSE
		SlowPushFailCount := SlowPushFailCount + 1;
	END_IF
	SlowPushUs := ULINT_TO_UDINT(NowUs() - StartUs);
	MaxSlowPushUs := MAX(MaxSlowPushUs, SlowPushUs);
END_IF

IF IsFastDue THEN
	StartUs := NowUs();
	SysTimeRtc.SysTimeRtcHighResGet(pTimestamp := StampMs);
	IF StampMs <= LastFastStampMs THEN
		StampMs := LastFastStampMs + 1;
	END_IF
	LastFastStampMs := StampMs;
	BuildStampMs := StampMs;
	BuildSeqKey := 'sfw_fast_seq:';
	BuildSeq := FastNextSeq;
	BuildTargetBytes := FastBytes;
	BuildPayload();
	IF IsTwoBlocksConfigured THEN
		IsPushed := BlockFast.Push(Topic := ADR(FastTopic), Payload := ADR(Payload), Length := Used);
	ELSE
		IsPushed := BlockSlow.Push(Topic := ADR(FastTopic), Payload := ADR(Payload), Length := Used);
	END_IF
	IF IsPushed THEN
		FastNextSeq := FastNextSeq + 1;
	ELSE
		FastPushFailCount := FastPushFailCount + 1;
	END_IF
	FastPushUs := ULINT_TO_UDINT(NowUs() - StartUs);
	MaxFastPushUs := MAX(MaxFastPushUs, FastPushUs);
END_IF

// Once per scan, after both streams' pushes: this scan's samples to the client, then backlog if admitted. BlockFast
// is called with one block too (not configured, it returns at once), so a mode change lets nothing hang.
StartUs := NowUs();
BlockSlow(AcceptPush := TRUE, Enable := TRUE, IsHoldOnNoSubscribers := IsHoldOnNoSubscribers,
	NoSubscriberPause := NoSubscriberPause, BacklogStartsPerCall := BacklogStartsPerCall,
	BacklogBytesPerCall := BacklogBytesPerCall, ReservedOutSlots := ReservedOutSlots, ReservedCredits := ReservedCredits,
	IsInferRefusals := FALSE);
SlowBlockUs := ULINT_TO_UDINT(NowUs() - StartUs);
MaxSlowBlockUs := MAX(MaxSlowBlockUs, SlowBlockUs);
StartUs := NowUs();
BlockFast(AcceptPush := TRUE, Enable := TRUE, IsHoldOnNoSubscribers := IsHoldOnNoSubscribers,
	NoSubscriberPause := NoSubscriberPause, BacklogStartsPerCall := BacklogStartsPerCall,
	BacklogBytesPerCall := BacklogBytesPerCall, ReservedOutSlots := ReservedOutSlots, ReservedCredits := ReservedCredits,
	IsInferRefusals := FALSE);
FastBlockUs := ULINT_TO_UDINT(NowUs() - StartUs);
MaxFastBlockUs := MAX(MaxFastBlockUs, FastBlockUs);

HasWork := BlockSlow.HasWork OR BlockFast.HasWork;
IsSendInFlight := BlockSlow.InFlightCount > 0 OR BlockFast.InFlightCount > 0;
IsLiveHandedOff := BlockSlow.IsLiveHandedOff OR BlockFast.IsLiveHandedOff;
IF IsLiveHandedOff THEN
	LiveHandOffScans := LiveHandOffScans + 1;
END_IF
