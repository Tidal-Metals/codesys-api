// TLS connect probe for the MQTT fork's TLS rework (tls_probe.py drives it). Runs in its own low-priority task
// (ProbeTask), as an application's PRG_Comms would. One attempt per DoConnect: a CmpTls context, a SysSocket2 TLS
// socket left NON-BLOCKING (the fork switches it to blocking for the connect, which froze the task), and
// SysSock2Connect called once per scan until it reports connected or TimeoutMs passes. Then an MQTT 3.1.1 CONNECT
// goes out and the CONNACK is read, which proves the handshake finished; then shutdown, close and free. Every
// distinct connect result, the calls that returned it and the longest single call are recorded.
// DoInstallCa adds CaDer (the bench test CA, DER, filled in by patch_demo_tls_probe.py) to the runtime's Trusted store.
PROGRAM TlsProbe
VAR
	// ---- commands, written online ----
	DoConnect : BOOL;
	DoInstallCa : BOOL;
	DoAbort : BOOL;
	TargetIp : DWORD := 16#C0A8326C;     // a.b.c.d as (a SHL 24) OR (b SHL 16) OR (c SHL 8) OR d: 192.168.50.108
	TargetPort : WORD := 8886;
	VerifyMode : DWORD := 2;              // CmpTls: TLS_VERIFY_NONE 1, TLS_VERIFY_PEER 2
	TimeoutMs : UDINT := 10000;           // handshake, and again for the CONNACK
	IsMqttConnectSent : BOOL := TRUE;
	IsVerifierUsed : BOOL := TRUE;        // CmpTlsCreateContext2 with Verifier (FALSE: CmpTlsCreateContext, no callback)
	IsHostCheckEnabled : BOOL := TRUE;    // Verifier rejects a certificate whose SAN doesn't name the broker
	IsIpExpected : BOOL := TRUE;          // FALSE: the broker's IP is not expected, only ExpectedDns can match
	ExpectedDns : STRING(80);

	// ---- results ----
	Verifier : TlsProbeVerifier;          // its outputs show what the callback saw
	IsBusy : BOOL;
	Attempt : UDINT;
	Outcome : STRING(40);
	ContextResult : UDINT;
	CreateResult : UDINT;
	IoctlResult : UDINT;
	ConnectCalls : UDINT;
	ConnectResults : ARRAY[0..7] OF UDINT;      // distinct SysSock2Connect results, in order of first appearance
	ConnectResultCalls : ARRAY[0..7] OF UDINT;  // calls that returned each
	ConnectResultCount : INT;
	LastConnectResult : UDINT;
	MaxConnectCallUs : UDINT;
	TotalConnectCallUs : UDINT;
	HandshakeMs : UDINT;
	SendResult : UDINT;
	SentBytes : DINT;
	RecvCalls : UDINT;
	RecvResult : UDINT;
	RecvBytes : DINT;
	Received : ARRAY[0..7] OF BYTE;
	MaxIoCallUs : UDINT;
	ShutdownResult : UDINT;
	CloseResult : UDINT;
	FreeResult : UDINT;
	CloseUs : UDINT;
	ScanCount : UDINT;
	MaxScanUs : UDINT;
	CaParseResult : UDINT;
	CaOpenResult : UDINT;
	CaAddResult : UDINT;
	CaStoreCloseResult : UDINT;
	CaCloseResult : UDINT;

	// ---- internals ----
	Step : INT;
	Context : SysTypes.RTS_IEC_HANDLE := SysTypes.RTS_INVALID_HANDLE;
	Socket : SysTypes.RTS_IEC_HANDLE := SysTypes.RTS_INVALID_HANDLE;
	Parameter : SysSocket2.SysSocket2_Parameter;
	Specific : SysSocket2.SysSocket2_SpecificParameter;
	Address : SysSocket2.SOCKADDRESS;
	NonBlocking : DINT := 1;
	CipherList : STRING(255) := 'HIGH';
	// MQTT 3.1.1 CONNECT, clean session, keep alive 60 s, client id "tlsprobe", no credentials (CONNACK 5 is fine)
	ConnectPacket : ARRAY[0..21] OF BYTE := [16#10, 20, 0, 4, 16#4D, 16#51, 16#54, 16#54, 4, 2, 0, 60, 0, 8,
		16#74, 16#6C, 16#73, 16#70, 16#72, 16#6F, 16#62, 16#65];
	ScanStartUs : ULINT;
	StartUs : ULINT;
	CallStartUs : ULINT;
	EndUs : ULINT;
	CallUs : UDINT;
	ElapsedMs : UDINT;
	ConnectResult : UDINT;
	I : INT;
	IsKnown : BOOL;
	CaBytes : TlsProbeByteString;
	CaCert : SysTypes.RTS_IEC_HANDLE := SysTypes.RTS_INVALID_HANDLE;
	CaStore : SysTypes.RTS_IEC_HANDLE := SysTypes.RTS_INVALID_HANDLE;
	CaDer : ARRAY[0..{CA_LAST}] OF BYTE := [{CA_BYTES}];
END_VAR
// ---- implementation ----
SysTimeCore.SysTimeGetUs(pUsTime := ScanStartUs);
ScanCount := ScanCount + 1;

IF DoInstallCa THEN
	DoInstallCa := FALSE;
	CaBytes.ui32MaxLen := SIZEOF(CaDer);
	CaBytes.ui32Len := SIZEOF(CaDer);
	CaBytes.pByData := ADR(CaDer);
	CaOpenResult := 0;
	CaAddResult := 0;
	CaStoreCloseResult := 0;
	CaCloseResult := 0;
	CaCert := CmpX509Cert.X509ParseCertificate(pCert := ADR(CaBytes), encoding := CmpX509Cert.RtsCertEncoding.ASN1,
		pResult := ADR(CaParseResult));
	IF CaParseResult = CmpErrors.Errors.ERR_OK THEN
		CaStore := CmpX509Cert.X509CertStoreOpen(componentID := 0, pResult := ADR(CaOpenResult));
		IF CaOpenResult = CmpErrors.Errors.ERR_OK THEN
			CaAddResult := CmpX509Cert.X509CertStoreAddCert(hCertStore := CaStore, hBackend := SysTypes.RTS_INVALID_HANDLE,
				hCert := CaCert, trustLevel := CmpX509Cert.RtsCertTrustLevel.Trusted);
			CaStoreCloseResult := CmpX509Cert.X509CertStoreClose(hCertStore := CaStore);
		END_IF
		CaCloseResult := CmpX509Cert.X509CertClose(hCert := CaCert);
	END_IF
END_IF

CASE Step OF
0:
	IF DoConnect THEN
		DoConnect := FALSE;
		DoAbort := FALSE;
		Attempt := Attempt + 1;
		IsBusy := TRUE;
		Outcome := 'connecting';
		ContextResult := 0; CreateResult := 0; IoctlResult := 0;
		ConnectCalls := 0; ConnectResultCount := 0; LastConnectResult := 0;
		FOR I := 0 TO 7 DO
			ConnectResults[I] := 0;
			ConnectResultCalls[I] := 0;
			Received[I] := 0;
		END_FOR
		MaxConnectCallUs := 0; TotalConnectCallUs := 0; HandshakeMs := 0;
		SendResult := 0; SentBytes := 0; RecvCalls := 0; RecvResult := 0; RecvBytes := 0; MaxIoCallUs := 0;
		ShutdownResult := 0; CloseResult := 0; FreeResult := 0; CloseUs := 0;
		Verifier.IsHostCheckEnabled := IsHostCheckEnabled;
		Verifier.ExpectedDns := ExpectedDns;
		IF IsIpExpected THEN
			Verifier.ExpectedIp := SysSocket2.SysSock2Ntohl(TargetIp);
		ELSE
			Verifier.ExpectedIp := 0;
		END_IF
		IF IsVerifierUsed THEN
			Context := CmpTls.CmpTlsCreateContext2(hCert := SysTypes.RTS_INVALID_HANDLE,
				tlsMethod := CmpTls.CmpTlsMethod.TLSv2_CLIENT, cipherList := ADR(CipherList), verifyMode := VerifyMode,
				verifyCallback := Verifier, pResult := ADR(ContextResult));
		ELSE
			Context := CmpTls.CmpTlsCreateContext(hCert := SysTypes.RTS_INVALID_HANDLE,
				tlsMethod := CmpTls.CmpTlsMethod.TLSv2_CLIENT, cipherList := ADR(CipherList), verifyMode := VerifyMode,
				pResult := ADR(ContextResult));
		END_IF
		IF ContextResult <> CmpErrors.Errors.ERR_OK THEN
			Outcome := 'context failed';
			Step := 90;
		ELSE
			Parameter.parameterType := SysSocket2.SysSocket2_Type.TLS;
			Specific.tlsSockets.hTlsContext := Context;
			Parameter.specific := Specific;
			Socket := SysSocket2.SysSock2Create(pParameter := ADR(Parameter), pResult := ADR(CreateResult));
			IF CreateResult <> CmpErrors.Errors.ERR_OK THEN
				Outcome := 'socket failed';
				Step := 90;
			ELSE
				IoctlResult := SysSocket2.SysSock2Ioctl(Socket, SysSocket2.GVL.SOCKET_FIONBIO, ADR(NonBlocking));
				Address.sin_family := SysSocket2.GVL.SOCKET_AF_INET;
				Address.sin_port := SysSocket2.SysSock2Ntohs(TargetPort);
				Address.sin_addr.ulAddr := SysSocket2.SysSock2Ntohl(TargetIp);
				SysTimeCore.SysTimeGetUs(pUsTime := StartUs);
				Step := 10;
			END_IF
		END_IF
	END_IF

10: // connect, once per scan
	SysTimeCore.SysTimeGetUs(pUsTime := CallStartUs);
	ConnectResult := SysSocket2.SysSock2Connect(Socket, ADR(Address), SIZEOF(Address));
	SysTimeCore.SysTimeGetUs(pUsTime := EndUs);
	CallUs := ULINT_TO_UDINT(EndUs - CallStartUs);
	ConnectCalls := ConnectCalls + 1;
	TotalConnectCallUs := TotalConnectCallUs + CallUs;
	MaxConnectCallUs := MAX(MaxConnectCallUs, CallUs);
	LastConnectResult := ConnectResult;
	IsKnown := FALSE;
	FOR I := 0 TO ConnectResultCount - 1 DO
		IF ConnectResults[I] = ConnectResult THEN
			ConnectResultCalls[I] := ConnectResultCalls[I] + 1;
			IsKnown := TRUE;
		END_IF
	END_FOR
	IF NOT IsKnown AND ConnectResultCount < 8 THEN
		ConnectResults[ConnectResultCount] := ConnectResult;
		ConnectResultCalls[ConnectResultCount] := 1;
		ConnectResultCount := ConnectResultCount + 1;
	END_IF
	HandshakeMs := ULINT_TO_UDINT((EndUs - StartUs) / 1000);
	IF ConnectResult = CmpErrors.Errors.ERR_OK OR ConnectResult = CmpErrors.Errors.ERR_SOCK_ISCONNECTED THEN
		Outcome := 'handshake done';
		StartUs := EndUs;
		IF IsMqttConnectSent THEN
			Step := 20;
		ELSE
			Step := 90;
		END_IF
	ELSIF ConnectResult <> CmpErrors.Errors.ERR_SOCK_WOULDBLOCK THEN
		// first probe run: ERR_SOCK_WOULDBLOCK (518) while in progress; ERR_FAILED (1) for a rejected certificate or
		// a peer that doesn't speak TLS, ERR_SOCK_HOSTUNREACHABLE (524) for a closed port: all final
		Outcome := 'connect failed';
		Step := 90;
	ELSIF DoAbort OR HandshakeMs > TimeoutMs THEN
		Outcome := 'connect timeout';
		Step := 90;
	END_IF

20: // send CONNECT
	SysTimeCore.SysTimeGetUs(pUsTime := CallStartUs);
	SentBytes := TO_DINT(SysSocket2.SysSock2Send(Socket, ADR(ConnectPacket), SIZEOF(ConnectPacket), 0, ADR(SendResult)));
	SysTimeCore.SysTimeGetUs(pUsTime := EndUs);
	MaxIoCallUs := MAX(MaxIoCallUs, ULINT_TO_UDINT(EndUs - CallStartUs));
	ElapsedMs := ULINT_TO_UDINT((EndUs - StartUs) / 1000);
	IF SentBytes = TO_DINT(SIZEOF(ConnectPacket)) THEN
		Outcome := 'CONNECT sent';
		StartUs := EndUs;
		Step := 30;
	ELSIF DoAbort OR ElapsedMs > TimeoutMs THEN
		Outcome := 'send failed';
		Step := 90;
	END_IF

30: // read CONNACK
	SysTimeCore.SysTimeGetUs(pUsTime := CallStartUs);
	RecvBytes := TO_DINT(SysSocket2.SysSock2Recv(Socket, ADR(Received), SIZEOF(Received), 0, ADR(RecvResult)));
	SysTimeCore.SysTimeGetUs(pUsTime := EndUs);
	MaxIoCallUs := MAX(MaxIoCallUs, ULINT_TO_UDINT(EndUs - CallStartUs));
	RecvCalls := RecvCalls + 1;
	ElapsedMs := ULINT_TO_UDINT((EndUs - StartUs) / 1000);
	IF RecvBytes > 0 THEN
		IF Received[0] = 16#20 THEN
			Outcome := 'CONNACK received';
		ELSE
			Outcome := 'unexpected reply';
		END_IF
		Step := 90;
	ELSIF DoAbort OR ElapsedMs > TimeoutMs THEN
		Outcome := 'no CONNACK';
		Step := 90;
	END_IF

90: // close
	SysTimeCore.SysTimeGetUs(pUsTime := CallStartUs);
	IF Socket <> SysTypes.RTS_INVALID_HANDLE THEN
		ShutdownResult := SysSocket2.SysSock2Shutdown(Socket, 0);
		CloseResult := SysSocket2.SysSock2Close(Socket);
		Socket := SysTypes.RTS_INVALID_HANDLE;
	END_IF
	IF Context <> SysTypes.RTS_INVALID_HANDLE THEN
		FreeResult := CmpTls.CmpTlsFreeContext(hTlsContext := Context);
		Context := SysTypes.RTS_INVALID_HANDLE;
	END_IF
	SysTimeCore.SysTimeGetUs(pUsTime := EndUs);
	CloseUs := ULINT_TO_UDINT(EndUs - CallStartUs);
	IsBusy := FALSE;
	Step := 0;
END_CASE

SysTimeCore.SysTimeGetUs(pUsTime := EndUs);
MaxScanUs := MAX(MaxScanUs, ULINT_TO_UDINT(EndUs - ScanStartUs));
