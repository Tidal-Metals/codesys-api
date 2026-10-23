PROGRAM OnlineChangeProbe
// online_change_test.py rewrites this implementation in the session project and logs in with an online change;
// ProbeValue then shows that the new code runs. It does not touch the MQTT client.
VAR
	ProbeValue : UDINT;
END_VAR
// ---- implementation ----
ProbeValue := 0;
