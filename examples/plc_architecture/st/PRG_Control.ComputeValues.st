// Action ComputeValues (step 3): engineering value and final quality for every input tag: the source's
// quality, downgraded to INVALID when the value is out of range or not a number. Derived values (recovery %,
// rejection %) go here too, computed only when their inputs are GOOD and the divisor is not zero.
// ---- implementation ----
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	IF NOT GVL_Tags.TagConfig[Index].IsWritable THEN
		GVL_Tags.Tags[Index].Value := GVL_Tags.Tags[Index].Raw * GVL_Tags.TagConfig[Index].Scale
			+ GVL_Tags.TagConfig[Index].Offset;
		GVL_Tags.Tags[Index].Quality := GVL_Tags.Tags[Index].SourceQuality;
		// Written as NOT (inside the range) so that NaN and infinity, which fail every comparison, are INVALID.
		IF GVL_Tags.Tags[Index].Quality = E_Quality.GOOD
				AND NOT (GVL_Tags.Tags[Index].Value >= GVL_Tags.TagConfig[Index].MinValue
					AND GVL_Tags.Tags[Index].Value <= GVL_Tags.TagConfig[Index].MaxValue) THEN
			GVL_Tags.Tags[Index].Quality := E_Quality.INVALID;
		END_IF
	END_IF
END_FOR
