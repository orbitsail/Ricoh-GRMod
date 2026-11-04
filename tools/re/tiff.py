"""Minimal TIFF/DNG tag reader (no external code). Reads IFD chains, SubIFDs, Exif IFD."""
import struct

TYPES = {1: ('B', 1), 2: ('s', 1), 3: ('H', 2), 4: ('I', 4), 5: ('II', 8), 6: ('b', 1), 7: ('B', 1),
         8: ('h', 2), 9: ('i', 4), 10: ('ii', 8), 11: ('f', 4), 12: ('d', 8), 13: ('I', 4)}


class Tiff:
    def __init__(self, data, base=0, order=None):
        self.d = data
        self.base = base
        if order is None:
            bo = data[base:base + 2]
            self.e = '<' if bo == b'II' else '>'
        else:
            self.e = order

    def u16(self, off):
        return struct.unpack_from(self.e + 'H', self.d, self.base + off)[0]

    def u32(self, off):
        return struct.unpack_from(self.e + 'I', self.d, self.base + off)[0]

    def first_ifd(self):
        return self.u32(4)

    def ifd(self, off):
        """Returns (entries dict tag -> (type, count, value_offset_or_inline_pos), next_offset)."""
        n = self.u16(off)
        ents = {}
        for k in range(n):
            p = off + 2 + 12 * k
            tag, typ, cnt = struct.unpack_from(self.e + 'HHI', self.d, self.base + p)
            size = TYPES.get(typ, ('B', 1))[1] * cnt
            vpos = p + 8 if size <= 4 else self.u32(p + 8)
            ents[tag] = (typ, cnt, vpos)
        nxt = self.u32(off + 2 + 12 * n)
        return ents, nxt

    def value(self, ent):
        typ, cnt, vpos = ent
        fmt, sz = TYPES.get(typ, ('B', 1))
        a = self.base + vpos
        if typ == 2:
            return self.d[a:a + cnt].split(b'\0')[0].decode('latin1')
        if typ == 7:
            return self.d[a:a + cnt]
        if typ in (5, 10):
            vals = struct.unpack_from(self.e + fmt[0] * (2 * cnt), self.d, a)
            out = [vals[2 * i] / vals[2 * i + 1] if vals[2 * i + 1] else float('nan') for i in range(cnt)]
            return out if cnt > 1 else out[0]
        vals = struct.unpack_from(self.e + fmt * cnt, self.d, a)
        return list(vals) if cnt > 1 else vals[0]


DNG_TAGS = {
    0x00FE: 'NewSubfileType', 0x0100: 'ImageWidth', 0x0101: 'ImageLength', 0x0102: 'BitsPerSample',
    0x0103: 'Compression', 0x0106: 'Photometric', 0x010F: 'Make', 0x0110: 'Model', 0x0111: 'StripOffsets',
    0x0112: 'Orientation', 0x0115: 'SamplesPerPixel', 0x0116: 'RowsPerStrip', 0x0117: 'StripByteCounts',
    0x0131: 'Software', 0x0132: 'DateTime', 0x0142: 'TileWidth', 0x0143: 'TileLength', 0x0144: 'TileOffsets',
    0x0145: 'TileByteCounts', 0x014A: 'SubIFDs', 0x828D: 'CFARepeatPatternDim', 0x828E: 'CFAPattern',
    0x8769: 'ExifIFD', 0xC612: 'DNGVersion', 0xC614: 'UniqueCameraModel', 0xC618: 'LinearizationTable',
    0xC619: 'BlackLevelRepeatDim', 0xC61A: 'BlackLevel', 0xC61D: 'WhiteLevel', 0xC61E: 'DefaultScale',
    0xC61F: 'DefaultCropOrigin', 0xC620: 'DefaultCropSize', 0xC621: 'ColorMatrix1', 0xC622: 'ColorMatrix2',
    0xC623: 'CameraCalibration1', 0xC624: 'CameraCalibration2', 0xC627: 'AnalogBalance',
    0xC628: 'AsShotNeutral', 0xC629: 'AsShotWhiteXY', 0xC62A: 'BaselineExposure', 0xC62B: 'BaselineNoise',
    0xC62C: 'BaselineSharpness', 0xC62E: 'LinearResponseLimit', 0xC630: 'LensInfo', 0xC633: 'ShadowScale',
    0xC634: 'DNGPrivateData', 0xC65A: 'CalibrationIlluminant1', 0xC65B: 'CalibrationIlluminant2',
    0xC68D: 'ActiveArea', 0xC68E: 'MaskedAreas', 0xC6F4: 'ProfileCalibrationSignature',
    0xC6F8: 'ProfileName', 0xC6FC: 'ProfileToneCurve', 0xC6FD: 'ProfileEmbedPolicy',
    0xC714: 'ForwardMatrix1', 0xC715: 'ForwardMatrix2', 0xC740: 'OpcodeList1', 0xC741: 'OpcodeList2',
    0xC74E: 'OpcodeList3', 0xC761: 'NoiseProfile', 0xC6FE: 'ProfileCopyright', 0xC71A: 'PreviewColorSpace',
    0xC725: 'ProfileLookTableDims', 0xC726: 'ProfileLookTableData', 0xC6F9: 'ProfileHueSatMapDims',
    0xC791: 'OriginalDefaultFinalSize', 0xC7A7: 'NewRawImageDigest', 0xC7A5: 'BaselineExposureOffset',
    0xC7A6: 'DefaultBlackRender', 0xC7A4: 'DefaultUserCrop',
    # Exif
    0x829A: 'ExposureTime', 0x829D: 'FNumber', 0x8822: 'ExposureProgram', 0x8827: 'ISO',
    0x8830: 'SensitivityType', 0x8832: 'RecommendedExposureIndex', 0x9003: 'DateTimeOriginal',
    0x9201: 'ShutterSpeedValue', 0x9202: 'ApertureValue', 0x9203: 'BrightnessValue',
    0x9204: 'ExposureCompensation', 0x9205: 'MaxApertureValue', 0x9207: 'MeteringMode',
    0x9208: 'LightSource', 0x9209: 'Flash', 0x920A: 'FocalLength', 0x927C: 'MakerNote',
    0xA402: 'ExposureMode', 0xA403: 'WhiteBalance', 0xA405: 'FocalLengthIn35mm', 0xA406: 'SceneCaptureType',
}


def read_all(path):
    data = open(path, 'rb').read()
    t = Tiff(data)
    out = {'_ifds': []}
    seen = set()

    def walk(off, name):
        if off == 0 or off in seen or off >= len(data):
            return
        seen.add(off)
        ents, nxt = t.ifd(off)
        rec = {}
        for tag, ent in ents.items():
            nm = DNG_TAGS.get(tag, f'0x{tag:04X}')
            try:
                v = t.value(ent) if ent[1] < 100000 else None
            except Exception:
                v = None
            rec[nm] = v
            rec.setdefault('_raw', {})[nm] = ent
        out['_ifds'].append((name, off, rec))
        if 0x014A in ents:
            subs = t.value(ents[0x014A])
            for k, s in enumerate(subs if isinstance(subs, list) else [subs]):
                walk(s, f'{name}.sub{k}')
        if 0x8769 in ents:
            walk(t.value(ents[0x8769]), f'{name}.exif')
        if nxt:
            walk(nxt, f'ifd{len([i for i in out["_ifds"] if "." not in i[0]])}')

    walk(t.first_ifd(), 'ifd0')
    return data, t, out
