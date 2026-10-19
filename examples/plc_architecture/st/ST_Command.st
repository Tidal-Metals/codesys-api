// One remote command, from the MQTT callback to the control task and back as an acknowledgement.
TYPE ST_Command :
STRUCT
	Id : UDINT;                 // sender's command id, echoed in the acknowledgement
	TagIndex : INT;             // resolved when received; 0 = unknown tag
	Value : REAL;
	SentAtMs : ULINT;           // wall-clock ms from the bridge, the one command sender
	ReceivedAtMs : ULINT;
	Result : E_CommandResult;
END_STRUCT
END_TYPE
