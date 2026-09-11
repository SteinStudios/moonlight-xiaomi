#!/usr/bin/env python3
"""
Porterer farnsworth3010's Amlogic-HEVC-fix ind i ClassicOldSong/moonlight-android (Artemis).

Root cause: Moonlight saetter 'low-latency' + 'vendor.low-latency.enable=1' paa
c2.amlogic.hevc.decoder. Netop de options haenger decoderen paa Amlogic S905X5M
(Xiaomi TV Box S 3rd Gen / TV Stick 4K Gen 2) -> sort skaerm.
Fix: spring low-latency-optionerne over for de beroerte modeller og brug kun
KEY_PRIORITY=0 (realtime). Desuden: HEVC RFI kun for Fire OS 7+, ikke alle c2.amlogic.

Kilde: https://github.com/farnsworth3010/moonlight-android-mi-tv-stick-gen-2
Upstream-issue: moonlight-stream/moonlight-android#1504

Idempotent. Fejler haardt (exit 1) hvis et anker mangler, saa CI stopper
i stedet for at producere en APK uden fixet.
"""
import sys
import pathlib

SRC = pathlib.Path("app/src/main/java/com/limelight/binding/video/MediaCodecHelper.java")
GRADLE = pathlib.Path("app/build.gradle")

if not SRC.exists():
    sys.exit(f"FEJL: {SRC} findes ikke - koeres scriptet fra repo-roden?")

txt = SRC.read_text(encoding="utf-8")
nl = "\r\n" if "\r\n" in txt else "\n"


def norm(s):
    """Match filens linjeskift (Artemis-kilden bruger CRLF)."""
    return s.replace("\n", nl)


def swap(text, anchor, replacement, errmsg):
    a = norm(anchor)
    if a not in text:
        sys.exit(errmsg)
    return text.replace(a, norm(replacement), 1)


# ============================================================ MediaCodecHelper
if "HEVC_LOW_LATENCY_BROKEN_MODEL_PATTERNS" in txt:
    print("MediaCodecHelper allerede patchet - springer over.")
else:
    before_len = len(txt)

    # --- 1. felter: model-liste + RFI-flag
    txt = swap(
        txt,
        '    private static boolean isLowEndSnapdragon = false;',
        '''    // === AMLOGIC HEVC FIX (porteret fra farnsworth3010/moonlight-android-mi-tv-stick-gen-2) ===
    // Disse modeller haenger c2.amlogic.hevc.decoder naar low-latency-options saettes.
    //   MDZ-33-AA / MDZ-32-AA   : Xiaomi TV Stick 4K (2nd Gen)
    //   MiTV-AFMU1              : samme, firmware-alias
    //   MiTV-AYFR0 / MiTV-AFMU0 : Xiaomi TV Box S (3rd Gen)
    private static final String[] HEVC_LOW_LATENCY_BROKEN_MODEL_PATTERNS = {
            "MDZ-33-AA",
            "MDZ-32-AA",
            "MiTV-AFMU1",
            "MiTV-AYFR0",
            "MiTV-AFMU0"
    };
    private static boolean isAmlogicRfiSafe = false;
    private static boolean isLowEndSnapdragon = false;''',
        "FEJL 1: anker 'isLowEndSnapdragon' ikke fundet",
    )

    # --- 2. Fire OS-grenen saetter flag i stedet for global c2.amlogic RFI
    txt = swap(
        txt,
        '''            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                refFrameInvalidationHevcPrefixes.add("omx.amlogic");
                refFrameInvalidationHevcPrefixes.add("c2.amlogic");
            }''',
        '''            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                // AMLOGIC HEVC FIX: RFI er kun bekraeftet sikkert paa Fire OS 7+.
                // Generelt for c2.amlogic giver det decoder-hang efter pakketab.
                isAmlogicRfiSafe = true;
                LimeLog.info("Enabling Amlogic HEVC RFI on Fire OS 7+ device");
            }''',
        "FEJL 2: Fire OS RFI-blok ikke fundet",
    )

    # --- 3. guard oeverst i setDecoderLowLatencyOptions (FOER alle andre options)
    txt = swap(
        txt,
        '''    public static boolean setDecoderLowLatencyOptions(MediaFormat videoFormat, MediaCodecInfo decoderInfo, boolean ultraLowLatency, int tryNumber) {
        // Options here should be tried in the order of most to least risky. The decoder will use
        // the first MediaFormat that doesn't fail in configure().

        boolean setNewOption = false;''',
        '''    private static boolean isHevcLowLatencyBrokenModel(String model) {
        if (model == null) {
            return false;
        }
        for (String pattern : HEVC_LOW_LATENCY_BROKEN_MODEL_PATTERNS) {
            if (model.equalsIgnoreCase(pattern)) {
                return true;
            }
        }
        return false;
    }

    public static boolean setDecoderLowLatencyOptions(MediaFormat videoFormat, MediaCodecInfo decoderInfo, boolean ultraLowLatency, int tryNumber) {
        // AMLOGIC HEVC FIX: skal ligge FOER alt andet, ellers naaes
        // 'low-latency' / 'vendor.low-latency.enable' alligevel.
        boolean isAffectedHevcDecoder =
                "video/hevc".equals(videoFormat.getString(MediaFormat.KEY_MIME))
                        && "c2.amlogic.hevc.decoder".equalsIgnoreCase(decoderInfo.getName())
                        && (isHevcLowLatencyBrokenModel(Build.MODEL) || isHevcLowLatencyBrokenModel(Build.DEVICE));

        if (isAffectedHevcDecoder) {
            if (tryNumber == 0 && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                LimeLog.info("Using realtime HEVC priority without low-latency options on affected TV stick model");
                videoFormat.setInteger(MediaFormat.KEY_PRIORITY, 0);
                return true;
            }
            return false;
        }

        // Options here should be tried in the order of most to least risky. The decoder will use
        // the first MediaFormat that doesn't fail in configure().

        boolean setNewOption = false;''',
        "FEJL 3: setDecoderLowLatencyOptions-signatur ikke fundet "
        "(forventer Artemis-varianten med 'boolean ultraLowLatency')",
    )

    # --- 4. RFI-heuristik: undtag ubekraeftede amlogic-decodere
    txt = swap(
        txt,
        '''        if (decoderSupportsAndroidRLowLatency(decoderInfo, "video/hevc") ||
                decoderSupportsKnownVendorLowLatencyOption(decoderInfo.getName())) {
            LimeLog.info("Enabling HEVC RFI based on low latency option support");
            return true;
        }''',
        '''        if (decoderSupportsAndroidRLowLatency(decoderInfo, "video/hevc") ||
                decoderSupportsKnownVendorLowLatencyOption(decoderInfo.getName())) {
            // AMLOGIC HEVC FIX
            if (!isDecoderInList(amlogicDecoderPrefixes, decoderInfo.getName())) {
                LimeLog.info("Enabling HEVC RFI based on low latency option support");
                return true;
            }
            else if (isAmlogicRfiSafe) {
                LimeLog.info("Enabling HEVC RFI on confirmed-safe Amlogic device");
                return true;
            }
            else {
                LimeLog.info("Not enabling HEVC RFI on unconfirmed Amlogic decoder: " + decoderInfo.getName());
            }
        }''',
        "FEJL 4: HEVC RFI-heuristik ikke fundet",
    )

    SRC.write_text(txt, encoding="utf-8")
    print(f"OK: MediaCodecHelper patchet (+{len(txt) - before_len} tegn)")


# ================================================================ build.gradle
# Side-by-side: officiel Artemis (com.limelight.noir) er signeret af
# ClassicOldSong. Vores build bruger debug-key -> signaturkonflikt ved install.
# Skift applicationId + label, saa begge kan ligge paa boksen samtidig.
if not GRADLE.exists():
    sys.exit("FEJL 5: app/build.gradle findes ikke")

g = GRADLE.read_text(encoding="utf-8")
if 'applicationIdSuffix ".noirhevc"' in g:
    print("build.gradle allerede patchet - springer over.")
else:
    before = g
    g = g.replace('applicationIdSuffix ".noir"', 'applicationIdSuffix ".noirhevc"', 1)
    g = g.replace('resValue "string", "app_label", "Artemis"',
                  'resValue "string", "app_label", "Artemis HEVC"', 1)
    g = g.replace('resValue "string", "app_label_game", "Artemis (Game)"',
                  'resValue "string", "app_label_game", "Artemis HEVC (Game)"', 1)
    if g == before:
        sys.exit("FEJL 5: build.gradle-ankre ikke fundet")
    GRADLE.write_text(g, encoding="utf-8")
    print("OK: build.gradle -> com.limelight.noirhevc / label 'Artemis HEVC'")
