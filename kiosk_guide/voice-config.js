/**
 * GIONG DOC CHO PHAN HUONG DAN (mot giong duy nhat: nam - mien Bac).
 *
 * File mp3 nam trong audio/ canh guide.js, ten file = id cua buoc + ".mp3"
 * (vd: welcome.mp3, scan-capture.mp3). Loi thoai tung file: guide-script.csv.
 *
 * Thieu file mp3 nao thi buoc do chi hien chu, huong dan van chay binh thuong.
 */
window.KIOSK_VOICE_CONFIG = {

    enabled: true,          // false = tat tieng, chi hien chu

    // dir: 'audio/',       // bo trong = tu tim audio/ canh guide.js; dat de tro sang noi khac
    ext: '.mp3',
    volume: 1.0             // 0.0 - 1.0
};
