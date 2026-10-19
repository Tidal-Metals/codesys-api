// Action ServeSnapshot (step 7): when the comms task asks (SnapshotRequest moved on), copy the whole tag
// table at once, inside this task, so a published message never mixes values from different scans.
// ---- implementation ----
IF GVL_Tags.SnapshotSequence <> GVL_Tags.SnapshotRequest THEN
	GVL_Tags.PublishSnapshot := GVL_Tags.Tags;
	GVL_Tags.SnapshotSequence := GVL_Tags.SnapshotRequest;
END_IF
