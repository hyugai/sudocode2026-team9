/** Approved Figma demonstration catalog; not a live inventory or checkout feed. */
export const categories = [
  { name: "Tất cả", icon: "a-imgFrame5.svg" },
  { name: "Điện tử", icon: "a-imgFrame6.svg" },
  { name: "Thời trang", icon: "a-imgFrame7.svg" },
  { name: "Nhà cửa", icon: "a-imgFrame8.svg" },
  { name: "Làm đẹp", icon: "a-imgFrame9.svg" },
  { name: "Nhà bếp", icon: "a-imgFrame8.svg" },
  { name: "Thể thao", icon: "a-imgFrame10.svg" },
] as const;

export const products = [
  { id: "airpods-2", name: "Tai nghe Apple AirPods 2 chính hãng", price: "2.490.000₫", rating: "4,9 · Đã bán 1,2k", category: "Điện tử", image: "a-imgProductPhoto.png" },
  { id: "puma-rider", name: "Giày Puma Future Rider unisex", price: "1.290.000₫", rating: "4,8 · Đã bán 862", category: "Thời trang", image: "a-imgProductPhoto1.png" },
  { id: "blender", name: "Máy xay sinh tố đa năng 1,5L", price: "890.000₫", rating: "4,9 · Đã bán 2,1k", category: "Nhà bếp", image: "a-imgProductPhoto2.png" },
  { id: "plant", name: "Chậu cây trang trí phong cách tối giản", price: "149.000₫", rating: "4,8 · Đã bán 3,4k", category: "Nhà cửa", image: "a-imgProductPhoto3.png" },
  { id: "olay", name: "Sữa tắm Olay dưỡng ẩm bơ hạt mỡ", price: "185.000₫", rating: "4,9 · Đã bán 5,6k", category: "Làm đẹp", image: "a-imgProductPhoto4.png" },
  { id: "airpods-max", name: "Tai nghe AirPods Max màu bạc", price: "10.990.000₫", rating: "4,9 · Đã bán 326", category: "Điện tử", image: "a-imgProductPhoto5.png" },
  { id: "macbook", name: "MacBook Pro 14 inch màu xám", price: "32.990.000₫", rating: "5,0 · Đã bán 178", category: "Điện tử", image: "a-imgProductPhoto6.png" },
  { id: "vaseline", name: "Sữa dưỡng thể Vaseline Men 400ml", price: "99.000₫", rating: "4,8 · Đã bán 4,2k", category: "Làm đẹp", image: "a-imgProductPhoto7.png" },
  { id: "bag", name: "Túi xách nữ đen thanh lịch", price: "329.000₫", rating: "4,8 · Đã bán 987", category: "Thời trang", image: "a-imgProductPhoto8.png" },
  { id: "football", name: "Bóng đá thể thao tiêu chuẩn số 5", price: "249.000₫", rating: "4,9 · Đã bán 754", category: "Thể thao", image: "a-imgProductPhoto9.png" },
] as const;
