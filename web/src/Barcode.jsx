// Draws a real EAN-13 / UPC-A symbol from its digits, so the coded-in demo products look like what they are.
const L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
const G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"];
const R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"];
const PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];

export function ean13Modules(code) {
  const digits = code.replace(/\D/g, "").padStart(13, "0").slice(-13);
  const parity = PARITY[Number(digits[0])];
  let bits = "101";
  for (let i = 1; i <= 6; i++) bits += (parity[i - 1] === "L" ? L : G)[Number(digits[i])];
  bits += "01010";
  for (let i = 7; i <= 12; i++) bits += R[Number(digits[i])];
  return bits + "101";
}

export default function Barcode({ code, height = 46 }) {
  const bits = ean13Modules(code);
  const bars = [];
  for (let i = 0; i < bits.length; i++) {
    if (bits[i] !== "1") continue;
    let w = 1;
    while (bits[i + w] === "1") w++;
    bars.push(<rect key={i} x={i} y="0" width={w} height={height} />);
    i += w - 1;
  }
  return (
    <svg className="barcode" viewBox={`0 0 ${bits.length} ${height}`} preserveAspectRatio="none" role="img" aria-label={`Barcode ${code}`}>
      {bars}
    </svg>
  );
}
