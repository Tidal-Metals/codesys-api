// ---- implementation ----
// The client loop: one call, and while any message is in flight more calls until ClientCallsPerScan or
// ClientBudgetUs. Called at the start of the scan, or at its end with IsClientCalledLast.
IsSendInFlight := LargePublisher.sendActive OR ConcatPublisher.sendActive OR TagValuePublisher.sendActive
	OR ScaleTest.Publisher.sendActive OR EdgeTest.Publisher.sendActive OR EdgeTest.EchoPublisher.sendActive;
StepStartUs := NowUs();
ClientCall := 0;
REPEAT
	MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ENABLE := TRUE, URL := BrokerUrl, TIMEOUT := T#10S, TLS := FALSE);
	ClientCall := ClientCall + 1;
UNTIL ClientCall >= ClientCallsPerScan
	OR_ELSE (IsClientLoopGated AND NOT IsSendInFlight)
	OR_ELSE NowUs() - StepStartUs >= ClientBudgetUs
END_REPEAT
MaxClientCalls := MAX(MaxClientCalls, ClientCall);
ClientUs := ULINT_TO_UDINT(NowUs() - StepStartUs);
MaxClientUs := MAX(MaxClientUs, ClientUs);
