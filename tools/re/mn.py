import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tiff import read_all, Tiff
PTAGS = {0x0000:'Version',0x0001:'ModelType',0x0002:'PreviewImageSize',0x0003:'PreviewImageLength',0x0004:'PreviewImageStart',
0x0005:'ModelID',0x0006:'Date',0x0007:'Time',0x0008:'Quality',0x0009:'PentaxImageSize',0x000C:'FlashMode',0x000D:'FocusMode',
0x000E:'AFPointSelected',0x000F:'AFPointsInFocus',0x0010:'FocusPosition',0x0012:'ExposureTime',0x0013:'FNumber',0x0014:'ISO',
0x0015:'LightReading',0x0016:'ExposureCompensation',0x0017:'MeteringMode',0x0018:'AutoBracketing',0x0019:'WhiteBalance',
0x001A:'WhiteBalanceMode',0x001B:'BlueBalance',0x001C:'RedBalance',0x001D:'FocalLength',0x001E:'DigitalZoom',0x001F:'Saturation',
0x0020:'Contrast',0x0021:'Sharpness',0x0022:'WorldTimeLocation',0x0023:'HometownCity',0x0024:'DestinationCity',
0x0025:'HometownDST',0x0026:'DestinationDST',0x0027:'DSPFirmwareVersion',0x0028:'CPUFirmwareVersion',0x0029:'FrameNumber',
0x002D:'EffectiveLV',0x0032:'ImageEditing',0x0033:'PictureMode',0x0034:'DriveMode',0x0035:'SensorSize',0x0037:'ColorSpace',
0x0038:'ImageAreaOffset',0x0039:'RawImageSize',0x003C:'AFPointsInFocus2',0x003D:'DataScaling',0x003E:'PreviewImageBorders',
0x003F:'LensRec',0x0040:'SensitivityAdjust',0x0041:'ImageEditCount',0x0047:'CameraTemperature',0x0048:'AELock',
0x0049:'NoiseReduction',0x004D:'FlashExposureComp',0x004F:'ImageTone',0x0050:'ColorTemperature',0x005C:'ShakeReductionInfo',
0x005D:'ShutterCount',0x0060:'FaceInfo',0x0062:'RawDevelopmentProcess',0x0067:'Hue',0x0068:'AWBInfo',
0x0069:'DynamicRangeExpansion',0x006B:'TimeInfo',0x006C:'HighLowKeyAdj',0x006D:'ContrastHighlight',0x006E:'ContrastShadow',
0x006F:'ContrastHighlightShadowAdj',0x0070:'FineSharpness',0x0071:'HighISONoiseReduction',0x0072:'AFAdjustment',
0x0073:'MonochromeFilterEffect',0x0074:'MonochromeToning',0x0076:'FaceDetect',0x0077:'FaceDetectFrameSize',
0x0079:'ShadowCorrection',0x007A:'ISOAutoParameters',0x007B:'CrossProcess',0x007D:'LensCorr',0x007E:'WhiteLevel',
0x007F:'BleachBypassToning',0x0080:'AspectRatio',0x0082:'BlurControl',0x0085:'HDR',0x0087:'ShutterType',
0x0088:'NeutralDensityFilter',0x008B:'ISO2',0x0092:'IntervalShooting',0x0095:'SkinToneCorrection',0x0096:'ClarityControl',
0x0200:'BlackPoint',0x0201:'WhitePoint',0x0203:'ColorMatrixA',0x0204:'ColorMatrixB',0x0205:'CameraSettings',0x0206:'AEInfo',
0x0207:'LensInfo',0x0208:'FlashInfo',0x0209:'AEMeteringSegments',0x020A:'FlashMeteringSegments',0x020B:'SlaveFlashMeteringSegments',
0x020D:'WB_RGGBLevelsDaylight',0x020E:'WB_RGGBLevelsShade',0x020F:'WB_RGGBLevelsCloudy',0x0210:'WB_RGGBLevelsTungsten',
0x0211:'WB_RGGBLevelsFluorescentD',0x0212:'WB_RGGBLevelsFluorescentN',0x0213:'WB_RGGBLevelsFluorescentW',
0x0214:'WB_RGGBLevelsFlash',0x0215:'CameraInfo',0x0216:'BatteryInfo',0x021B:'SaturationInfo',0x021C:'ColorMatrixA2',
0x021D:'ColorMatrixB2',0x021F:'AFInfo',0x0220:'HuffmanTable',0x0221:'KelvinWB',0x0222:'ColorInfo',0x0224:'EVStepInfo',
0x0226:'ShotInfo',0x0227:'FacePos',0x0228:'FaceSize',0x0229:'SerialNumber',0x022A:'FilterInfo',0x022B:'LevelInfo',
0x022E:'Artist',0x022F:'Copyright',0x0230:'FirmwareVersion',0x0231:'ContrastDetectAFArea',0x0235:'CrossProcessParams',
0x0239:'LensInfoQ',0x023F:'LensCorr2',0x0243:'PixelShiftInfo',0x0245:'AFPointInfo',0x03FE:'DataDump',0x03FF:'TempInfo',
0x0402:'ToneCurve',0x0403:'ToneCurves',0x0405:'UnknownBlock',0x0E00:'PrintIM'}
def load_mn(path):
    data, t, out = read_all(path)
    rec = out['_ifds'][0][2]
    typ, cnt, vpos = rec['_raw']['DNGPrivateData']
    mt = Tiff(data, base=vpos, order='<')
    ents, nxt = mt.ifd(8)
    return data, t, out, mt, ents, vpos, cnt
if __name__ == '__main__':
    data, t, out, mt, ents, vpos, cnt = load_mn(sys.argv[1])
    print('entries', len(ents), 'privsize', cnt)
    for tag, ent in sorted(ents.items()):
        typ, n, pos = ent
        nm = PTAGS.get(tag, f'0x{tag:04X}')
        sz = n * {1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8}.get(typ,1)
        if sz <= 64:
            v = mt.value(ent)
            if isinstance(v, bytes): v = v.hex()
            print(f'{tag:04X} {nm:28s} t{typ} n{n} {v}')
        else:
            raw = data[vpos+pos:vpos+pos+min(sz,48)]
            print(f'{tag:04X} {nm:28s} t{typ} n{n} @{pos} <{sz}B> {raw.hex()}')
