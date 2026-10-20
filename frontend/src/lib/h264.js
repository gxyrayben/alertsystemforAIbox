/**
 * H.264 AnnexB 工具：把设备推来的 NAL 流整理成 WebCodecs (`VideoDecoder`) 需要的形式。
 *
 * 设备实测（1920×1080 H264）：
 *   - 关键帧：`00 00 00 01 06 05 ..`（SEI）后跟 SPS(7) / PPS(8) / IDR(5)，参数集**在带内**；
 *   - 普通帧：`00 00 00 01 41 9a ..`（type=1 非 IDR 切片）。
 * 起始码 3 字节 `00 00 01` 与 4 字节 `00 00 00 01` 都要支持。
 *
 * WebCodecs 的 `avc1.*` 要求：
 *   - `configure({ codec, description })`，description 是 AVCDecoderConfigurationRecord(avcC)，
 *     由 SPS/PPS 构造；
 *   - `decode()` 的每一帧数据用 **AVCC**（每个 NAL 前加 4 字节大端长度），不是 AnnexB。
 *   所以这里做：切 NAL → 取 SPS/PPS → 造 avcC → 帧转 AVCC。
 */

/** 切出所有 NAL 负载（不含起始码）。兼容 3/4 字节起始码与末尾无起始码的情况。 */
export function splitNals(u8) {
    const nals = [];
    let i = 0;
    const len = u8.length;
    let start = -1;
    while (i + 2 < len) {
        // 找起始码
        if (u8[i] === 0 && u8[i + 1] === 0 && u8[i + 2] === 1) {
            if (start >= 0) nals.push(u8.subarray(start, i));
            i += 3;
            start = i;
        } else {
            i += 1;
        }
    }
    if (start >= 0 && start < len) nals.push(u8.subarray(start, len));
    // 过滤空 NAL 与全零填充
    return nals.filter((n) => n.length > 0);
}

/** NAL 类型（nal_unit_type，H.264 为低 5 位）。1 非IDR切片 / 5 IDR / 7 SPS / 8 PPS / 6 SEI */
export function nalType(nal) {
    return nal.length ? nal[0] & 0x1f : -1;
}

/** 从 SPS 构造 WebCodecs 的 codec 字符串：avc1.<profile><constraint><level>，各 2 位十六进制。 */
export function spsToCodecString(sps) {
    if (!sps || sps.length < 4) return '';
    const hex = (v) => (v < 16 ? '0' : '') + v.toString(16);
    // SPS: [0]=NAL头 [1]=profile_idc [2]=constraint_flags [3]=level_idc
    return 'avc1.' + hex(sps[1]) + hex(sps[2]) + hex(sps[3]);
}

/** 由 SPS + PPS 构造 AVCDecoderConfigurationRecord（avcC），供 VideoDecoder.configure 的 description 用。 */
export function buildAvcC(sps, pps) {
    if (!sps || !pps || sps.length < 4 || !pps.length) return null;
    const parts = [
        0x01,            // configurationVersion
        sps[1],          // AVCProfileIndication
        sps[2],          // profile_compatibility
        sps[3],          // AVCLevelIndication
        0xff,            // 6 bits reserved(111111) + lengthSizeMinusOne(11 => 4字节长度)
        0xe0 | 0x01,     // 3 bits reserved(111) + numOfSequenceParameterSets(1)
        (sps.length >> 8) & 0xff, sps.length & 0xff,
    ];
    const out = [];
    parts.forEach((b) => out.push(b));
    sps.forEach((b) => out.push(b));
    out.push(0x01);      // numOfPictureParameterSets
    out.push((pps.length >> 8) & 0xff, pps.length & 0xff);
    pps.forEach((b) => out.push(b));
    return new Uint8Array(out);
}

/** AnnexB → AVCC：每个 NAL 前面加 4 字节大端长度。 */
export function annexbToAvcc(u8) {
    const nals = splitNals(u8);
    let total = 0;
    for (const n of nals) total += 4 + n.length;
    const out = new Uint8Array(total);
    let off = 0;
    for (const n of nals) {
        const len = n.length;
        out[off] = (len >>> 24) & 0xff;
        out[off + 1] = (len >>> 16) & 0xff;
        out[off + 2] = (len >>> 8) & 0xff;
        out[off + 3] = len & 0xff;
        out.set(n, off + 4);
        off += 4 + len;
    }
    return out;
}

/**
 * 解析一帧 AnnexB 数据，产出驱动 VideoDecoder 所需的信息。
 * 返回 { nals, sps, pps, idr, avcc }
 *   - sps/pps：本帧内出现的参数集（可能为空，普通帧不带）
 *   - idr    ：本帧是否含 IDR 切片（或带了 SPS，可视为可解码起点）
 */
export function analyzeFrame(u8) {
    const nals = splitNals(u8);
    let sps = null, pps = null, idr = false;
    for (const n of nals) {
        const t = nalType(n);
        if (t === 7) sps = n;
        else if (t === 8) pps = n;
        else if (t === 5) idr = true;
    }
    if (sps) idr = true;          // 带参数集的帧一定是关键帧
    return { nals, sps, pps, idr, avcc: annexbToAvcc(u8) };
}
