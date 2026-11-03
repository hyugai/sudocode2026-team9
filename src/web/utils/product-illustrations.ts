/** Demo artwork only. Catalog identity, prices and stock still come from the API. */
const illustrationGroups: Record<string, readonly string[]> = {
  "air-purifier": ["SKU-AP-X", "SKU-AP-Y", "SKU-AP-MINI", "SKU-AP-PRO", "SKU-XM-4L", "SKU-XM-4P", "SKU-SS-AX40", "SKU-AP-X-2024"],
  "water-purifier": ["SKU-WF-RO9", "SKU-WF-RO10", "SKU-WF-UF"],
  "standing-fan": ["SKU-FAN-DC1", "SKU-FAN-SEN"],
  "tower-fan": ["SKU-FAN-TWR"],
  "air-fryer": ["SKU-AF-4L", "SKU-AF-6L", "SKU-AF-XM"],
  "running-shoes": ["SKU-SN-RUN1", "SKU-SN-RUN2", "SKU-SN-CAS", "SKU-SN-RUN1-OLD"],
  "hiking-shoes": ["SKU-SN-TRK"],
  "windbreaker": ["SKU-JK-WND"],
  "puffer-jacket": ["SKU-JK-DWN"],
  "breast-pump": ["SKU-MB-PUMP1", "SKU-MB-PUMP2"],
  "stroller": ["SKU-MB-STR1", "SKU-MB-STR2"],
  "bottle-warmer": ["SKU-MB-MON"],
  "sterilizer": ["SKU-MB-STER"],
  "baby-bottle": ["SKU-MB-BOT"],
  "car-seat": ["SKU-MB-CAR"],
  "air-purifier-bundle": ["SKU-BDL-AIR"],
  "breastfeeding-bundle": ["SKU-BDL-MOM"],
  "air-filter": ["SKU-AP-FLT-X", "SKU-AP-FLT-P", "SKU-XM-FLT"],
  "water-filters": ["SKU-WF-CORE"],
  "sports-socks": ["SKU-SN-SOCK"],
  "milk-storage-bags": ["SKU-MB-BAG"],
};

const illustrations = new Map(Object.entries(illustrationGroups)
  .flatMap(([image, skus]) => skus.map(sku => [sku, `/products/illustrations/${image}.webp`] as const)));

export function productIllustrationFor(sku: string): string | undefined {
  return illustrations.get(sku);
}
