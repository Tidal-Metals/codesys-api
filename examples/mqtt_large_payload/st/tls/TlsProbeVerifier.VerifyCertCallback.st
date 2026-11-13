METHOD VerifyCertCallback : SysTypes.RTS_IEC_RESULT
VAR_INPUT
	hCert : SysTypes.RTS_IEC_HANDLE;
	verifyResult : SysTypes.RTS_IEC_RESULT;
END_VAR
// ---- implementation ----
Calls := Calls + 1;
LastVerifyResult := verifyResult;
IsHostMatched := FALSE;
LastHostCheckResult := 0;
LastAltNameCount := 0;
FOR I := 0 TO 3 DO
	AltTypes[I] := -1;
	AltIps[I] := 0;
END_FOR
AltDns[0] := '';
AltDns[1] := '';
DnsCount := 0;

// Diagnostics only: the SubjectAltNames, read into Info and released again (X509CertInfoInit/Exit)
IF IsSanDumped THEN
	LastContentResult := CmpX509Cert.X509CertInfoInit(pCertInfo := ADR(Info), structSize := SIZEOF(Info));
	IF LastContentResult = CmpErrors.Errors.ERR_OK THEN
		LastContentResult := CmpX509Cert.X509CertGetContent(hCert := hCert, pCertContent := ADR(Info));
		IF LastContentResult = CmpErrors.Errors.ERR_OK THEN
			LastAltNameCount := Info.numOfAltNames;
			Alt := Info.pAltNames;
			I := 0;
			WHILE Alt <> 0 AND I < Info.numOfAltNames AND I < 4 DO
				AltTypes[I] := TO_INT(Alt^.valueType);
				IF Alt^.valueType = CmpX509Cert.RtsX509AltNameType.IpAddress THEN
					AltIps[I] := Alt^.value.ipAddress.ulAddr;
				ELSIF Alt^.valueType = CmpX509Cert.RtsX509AltNameType.DnsName AND Alt^.value.pDnsName <> 0 AND DnsCount < 2 THEN
					AltDns[DnsCount] := Alt^.value.pDnsName^;
					DnsCount := DnsCount + 1;
				END_IF
				Alt := Alt + SIZEOF(CmpX509Cert.RtsX509AltName);
				I := I + 1;
			END_WHILE
		END_IF
		LastExitResult := CmpX509Cert.X509CertInfoExit(pCertInfo := ADR(Info));
	END_IF
END_IF

// The decision: exactly one reference identity, checked by the runtime (OpenSSL's matcher)
IF ExpectedDns <> '' THEN
	IsHostMatched := CmpX509Cert.X509CertCheckHost(hCert := hCert, pHost := ADR(ExpectedDns),
		flags := CmpX509Cert.RtsX509CertCheckFlags.DISABLE_PARTIAL_WILDCARDS, pResult := ADR(LastHostCheckResult));
	CheckedBy := 'name';
ELSIF ExpectedIp <> 0 THEN
	CheckIp.ulAddr := ExpectedIp;
	IsHostMatched := CmpX509Cert.X509CertCheckIP(hCert := hCert, pIP := ADR(CheckIp), flags := 0,
		pResult := ADR(LastHostCheckResult));
	CheckedBy := 'ip';
ELSE
	CheckedBy := 'none';
END_IF

IF verifyResult <> CmpErrors.Errors.ERR_OK THEN
	LastReturn := verifyResult;
ELSIF IsHostCheckEnabled AND NOT IsHostMatched THEN
	LastReturn := CmpErrors.Errors.ERR_FAILED;
ELSE
	LastReturn := CmpErrors.Errors.ERR_OK;
END_IF
VerifyCertCallback := LastReturn;
