# Tóm tắt nội dung  
## Đề xuất tự động hóa Tài chính & Kế toán cho doanh nghiệp FMCG

**Đơn vị đề xuất:** BnK Solution  
**Giải pháp cốt lõi:** BnK IDP + RPA Orchestration  
**Phạm vi:** Tài chính – kế toán ngành FMCG  
**Đối tượng trình bày:** Ban lãnh đạo, CEO, CFO  
**Năm:** 2026  

---

## 1. Tóm tắt điều hành

Doanh nghiệp FMCG quy mô lớn thường phải xử lý hàng triệu chứng từ mỗi năm trên nhiều nhà máy, công ty con, kênh phân phối MT/GT và nhiều hệ thống rời rạc. Những vấn đề nổi bật gồm:

- Chi phí khuyến mãi và trade spend khó kiểm soát.
- Deductions, chargeback và công nợ nhà phân phối dễ phát sinh thất thoát.
- Nhân sự phải thao tác thủ công trên nhiều cổng siêu thị, ERP, DMS và ngân hàng.
- Chu kỳ đóng sổ kéo dài, dữ liệu cập nhật chậm.
- Dòng tiền phân tán và dự báo thiếu chính xác.

BnK đề xuất triển khai **BnK IDP kết hợp RPA** cho bốn nhóm quy trình:

1. Purchase to Pay — Mua sắm đến Thanh toán.
2. Order to Cash — Đặt hàng đến Thu tiền.
3. Record to Report — Ghi sổ đến Báo cáo.
4. Treasury — Ngân quỹ.

Giải pháp tích hợp trực tiếp với SAP/Oracle ERP, DMS, TMS và hệ thống ngân hàng mà không cần thay thế toàn bộ hệ thống hiện hữu. Quản trị, phân quyền, kiểm soát ngoại lệ và nhật ký kiểm toán được thiết kế ngay từ đầu.

Đề xuất triển khai theo mô hình **pilot 90 ngày trên 1–2 quy trình ưu tiên**, đo lường kết quả thực tế trước khi mở rộng toàn doanh nghiệp.

---

## 2. Các thách thức tài chính đặc thù của ngành FMCG

### 2.1. Thất thoát chi phí khuyến mãi

Ngân sách trade spend thường được theo dõi bằng bảng tính rời rạc, dẫn đến:

- Chi vượt ngân sách.
- Chi sai chương trình.
- Khó phát hiện thất thoát kịp thời.
- Thiếu dữ liệu tức thời cho bộ phận tài chính.

### 2.2. Deductions và chargeback từ kênh MT

Siêu thị và chuỗi bán lẻ có thể cấn trừ nhiều loại phí như:

- Phí trưng bày.
- Phạt giao hàng.
- Phí hàng hư hỏng.
- Chiết khấu và hỗ trợ thương mại.

Thiếu quy trình đối soát tự động khiến doanh nghiệp mất tiền âm thầm.

### 2.3. Công nợ nhà phân phối phức tạp

Đặc thù kênh GT gồm:

- Hạn mức tín dụng.
- Bán gối đầu.
- Hàng đổi trả.
- Cấn trừ khuyến mãi.
- Số lượng lớn điểm bán và nhà phân phối.

Việc theo dõi thủ công dễ dẫn đến dữ liệu rời rạc và khó kiểm soát rủi ro tín dụng.

### 2.4. Cao điểm mùa vụ và dữ liệu omnichannel

Trong mùa Tết hoặc các đợt khuyến mãi, khối lượng đơn hàng và chứng từ tăng mạnh. Nhân viên phải đăng nhập thủ công vào nhiều cổng siêu thị để lấy đơn hàng, tạo ra áp lực vận hành lớn.

### 2.5. Đóng sổ chậm

Việc hợp nhất dữ liệu từ nhiều ERP, nhà máy, công ty con và nhãn hàng khiến chu kỳ đóng sổ kéo dài, ảnh hưởng tốc độ ra quyết định.

### 2.6. Dòng tiền phân tán

Tiền mặt nằm trên nhiều tài khoản ngân hàng, đơn vị thành viên và kênh phân phối. Doanh nghiệp khó tổng hợp vị thế tiền mặt và dự báo chính xác.

---

## 3. Kiến trúc giải pháp tổng thể

Luồng dữ liệu được thiết kế xuyên suốt từ nguồn đầu vào đến hệ thống lõi và lớp giám sát.

### 3.1. Nguồn dữ liệu

- Hóa đơn nhà cung cấp.
- Đơn hàng nhà phân phối và DMS.
- Cổng siêu thị thuộc kênh MT.
- Sao kê ngân hàng.
- Email, EDI và hóa đơn điện tử.
- PDF, ảnh scan và chứng từ viết tay.

### 3.2. Lớp BnK IDP + RPA

#### BnK IDP

- Đọc và bóc tách dữ liệu từ nhiều loại chứng từ.
- Trích xuất các trường dữ liệu cần thiết.
- Xử lý PDF, ảnh scan, hóa đơn điện tử và chữ viết tay.
- Có khả năng thích nghi với mẫu chứng từ mới.

#### RPA Orchestrator

- Robot thao tác trực tiếp trên ERP, DMS, TMS và ngân hàng.
- Thực thi nghiệp vụ theo business rules.
- Chạy liên tục 24/7.
- Tự động nhập liệu, đối chiếu, tạo bút toán và gửi thông báo.

#### Exception Queue

- Các giao dịch khớp đúng được xử lý tự động.
- Các trường hợp sai lệch được chuyển cho kế toán kiểm tra.
- Con người vẫn giữ quyền phê duyệt cuối cùng.

### 3.3. Hệ thống lõi

- SAP hoặc Oracle ERP.
- DMS.
- TMS ngân quỹ.
- Core Banking.
- Hệ thống hóa đơn điện tử.
- BI và dashboard.

### 3.4. Đầu ra và giám sát

- Dashboard thời gian thực.
- Báo cáo tài chính tự sinh.
- Nhật ký kiểm toán từng bước.
- Cảnh báo ngoại lệ.
- Theo dõi hiệu suất robot và quy trình.

### 3.5. Governance & Compliance

Giải pháp tích hợp sẵn:

- Phân quyền theo vai trò và hạn mức.
- Nhật ký kiểm toán.
- Kiểm soát ngoại lệ.
- Bảo mật và lưu vết dữ liệu.
- Human-in-the-loop.
- Khả năng phục vụ kiểm toán nội bộ, kiểm toán độc lập và cơ quan thuế.

---

## 4. Bốn năng lực nền tảng

### 4.1. Đọc chứng từ

BnK IDP có thể:

- Đọc PDF, ảnh scan, hóa đơn điện tử và chữ viết tay.
- Trích xuất hơn 15 trường dữ liệu.
- Tự học và thích nghi với mẫu mới.

Theo tài liệu, một hóa đơn nhà cung cấp có thể được xử lý trong dưới 30 giây thay vì khoảng 8 phút nhập tay.

### 4.2. Thao tác hệ thống

RPA Bots có thể:

- Đăng nhập ERP, DMS và ngân hàng.
- Nhập liệu.
- Đối chiếu.
- Tạo bút toán.
- Gửi thông báo.
- Vận hành 24/7.

### 4.3. Kiểm soát ngoại lệ

- Giao dịch hợp lệ được tự động xử lý.
- Giao dịch lệch được chuyển vào hàng đợi.
- Kế toán xem xét và phê duyệt.
- Robot không thay thế quyền quyết định của con người trong các trường hợp rủi ro.

### 4.4. Phân tích và quản trị

- Dashboard thời gian thực.
- Nhật ký xử lý đầy đủ.
- Phân quyền phê duyệt.
- Hỗ trợ kiểm toán và tuân thủ.

---

## 5. Nhóm quy trình 1 — Purchase to Pay

### Luồng xử lý

1. Tiếp nhận hóa đơn từ email, EDI hoặc bản scan.
2. IDP bóc tách hơn 15 trường dữ liệu.
3. Khớp ba chiều PO – GR – Invoice.
4. Chuyển sai lệch giá hoặc số lượng cho AP duyệt.
5. Tạo bút toán, xếp lịch chi và thông báo nhà cung cấp.

### Trước tự động hóa

- Nhập tay gần như hoàn toàn.
- Mỗi hóa đơn mất 3–5 ngày đi qua nhiều khâu.
- Khó xử lý các tình huống nhiều PO, nhiều hóa đơn và nhiều phiếu nhập.
- Khó kiểm soát hàng khuyến mãi và hợp đồng khung nhiều đơn giá.

### Sau tự động hóa

- Trên 70% hóa đơn có thể xử lý xuyên suốt.
- Khớp ba chiều gần như tức thời.
- Chi trả đúng hạn.
- Giảm thao tác thủ công.

### KPI được nêu

- Độ chính xác khớp ba chiều trên 99%.

---

## 6. Nhóm quy trình 2 — Order to Cash

### Luồng xử lý

1. Bot lấy đơn từ DMS và cổng siêu thị.
2. Kiểm tra hạn mức tín dụng và tồn kho.
3. Tạo sales order.
4. Phát hành hóa đơn điện tử.
5. Đối soát báo có ngân hàng.
6. Cấn trừ khuyến mãi và deductions.
7. Cập nhật công nợ và nhắc nợ.

### Trước tự động hóa

- Nhân viên đăng nhập thủ công vào nhiều cổng MT.
- Dễ sai sót khi lập hóa đơn.
- DSO cao.
- Tranh chấp chiết khấu xử lý thủ công.

### Sau tự động hóa

- Bot lấy đơn từ nhiều kênh.
- Hóa đơn được tạo tự động.
- Thu tiền được tự động khớp.
- Deductions và công nợ nhà phân phối minh bạch hơn.
- Dữ liệu cập nhật gần thời gian thực.

### KPI được nêu

- Mục tiêu không phát sinh lỗi trong khâu lập hóa đơn.

---

## 7. Nhóm quy trình 3 — Record to Report

### Luồng xử lý

1. Thu thập dữ liệu từ nhiều ERP và nhà máy.
2. Tự tạo journal và phân bổ chi phí.
3. Đối chiếu liên công ty, ngân hàng và sub-ledger với GL.
4. Hợp nhất dữ liệu đa nhãn hàng và công ty con.
5. Tạo dashboard và báo cáo tài chính.

### Trước tự động hóa

- Đóng sổ mất khoảng 8–10 ngày.
- Phân bổ chi phí khuyến mãi thủ công.
- Đối chiếu dễ sai.
- Số liệu quản trị về chậm.

### Sau tự động hóa

- Fast close còn khoảng 3 ngày.
- Đối chiếu được tự động hóa.
- Dữ liệu hợp nhất cập nhật nhanh hơn.
- Ban lãnh đạo có thông tin kịp thời hơn.

### KPI được nêu

- Giảm khoảng 70% thời gian xử lý và đối chiếu báo cáo.

---

## 8. Nhóm quy trình 4 — Treasury

### Luồng xử lý

1. Lấy sao kê từ nhiều ngân hàng và TMS.
2. Hợp nhất cash position toàn tập đoàn.
3. Đối soát giao dịch, bao gồm tiền mặt kênh GT.
4. Cập nhật dự báo dòng tiền.
5. Cảnh báo tiền nhàn rỗi và đề xuất cơ hội đầu tư.

### Trước tự động hóa

- Đối soát và dự báo chủ yếu làm cuối kỳ.
- Nhiều thao tác thủ công.
- Tiền nhàn rỗi cao.
- Khó nhìn tổng thể dòng tiền.

### Sau tự động hóa

- Vị thế tiền mặt được cập nhật 24/7.
- Đối soát liên tục.
- Dự báo dòng tiền đáng tin cậy hơn.
- Bộ phận ngân quỹ chủ động điều tiết thanh khoản.

### KPI được nêu

- Giám sát vị thế tiền mặt 24/7.

---

## 9. Minh họa một hóa đơn đi qua hệ thống

Tài liệu mô tả một tình huống thực tế:

- **09:02:** Hóa đơn PDF được gửi vào IDP Inbox.
- **09:02:** IDP trích 16 trường trong 28 giây, độ tin cậy 97%.
- **09:03:** RPA thực hiện khớp PO – GR – Invoice trong SAP.
- Phát hiện chênh lệch giá 0,4%.
- **11:15:** Kế toán xem xét ngoại lệ và duyệt trong 2 phút.
- **11:17:** Bot tạo bút toán, xếp lịch thanh toán và báo nhà cung cấp.

Con người chỉ cần thao tác khoảng **2 phút**, thay vì 8–12 phút xử lý cộng thêm 2–3 ngày chờ qua nhiều khâu.

---

## 10. Business Case

### Chi phí đầu tư năm đầu

Bao gồm:

- License.
- Triển khai.
- Đào tạo.
- Quản trị thay đổi.

Giá trị cụ thể hiện đang để dạng placeholder **[X] tỷ đồng** và cần được xác định sau workshop.

### Giá trị thu về hàng năm

Nguồn lợi ích gồm:

- Giảm giờ công.
- Giảm thất thoát trade spend.
- Giảm deductions và các khoản phạt.
- Giảm lỗi nhập liệu và đối soát.
- Cải thiện vòng quay tiền.

Giá trị hiện đang để dạng placeholder **[Y] tỷ đồng**.

### Chỉ số tài chính kỳ vọng

- Thời gian hoàn vốn: khoảng 8–14 tháng.
- ROI 3 năm: khoảng 2,5–4 lần tổng chi phí sở hữu.

BnK đề xuất xây business case trên dữ liệu thực của doanh nghiệp và cam kết KPI đo lường được.

---

## 11. Năng lực và kinh nghiệm của BnK

### VitaDairy

- Tự động hóa hóa đơn đầu vào.
- Đối soát công nợ nhà phân phối.
- Tích hợp trực tiếp ERP.
- Phù hợp đặc thù ngành sữa và FMCG.

### AIG — Tập đoàn Nguyên liệu Á Châu

- Tự động hóa tài chính back-office.
- Phạm vi bao gồm R&D, sản xuất, phân phối và logistics.
- Chú trọng kiểm soát và tuân thủ.

### Jevu — Indonesia

- Triển khai tự động hóa tài chính cho ngành hàng tiêu dùng.
- Chứng minh khả năng mở rộng sang mô hình vận hành đa quốc gia.

### Năng lực tổ chức

- Hơn 350 chuyên gia.
- 5 văn phòng tại Việt Nam, Singapore và Nhật Bản.
- Hỗ trợ vận hành 24/7 sau triển khai.

---

## 12. Vì sao chọn BnK

- Có hiểu biết nghiệp vụ P2P, O2C, R2R và Treasury.
- Am hiểu đặc thù kế toán và tài chính FMCG.
- Làm chủ cả IDP và RPA trong một chuỗi end-to-end.
- Một đối tác chịu trách nhiệm xuyên suốt.
- Governance và compliance được tích hợp ngay từ thiết kế.
- Có kinh nghiệm triển khai thực tế trong và ngoài Việt Nam.
- Có khả năng tích hợp với hệ thống hiện hữu thay vì yêu cầu thay mới.

---

## 13. Lộ trình triển khai 90 ngày

### Tuần 1–3 — Khảo sát và Business Case

- Workshop các quy trình P2P, O2C, R2R và Treasury.
- Đo baseline về khối lượng, thời gian và sai sót.
- Xác định phạm vi pilot.
- Chốt KPI hoàn vốn.

### Tuần 4–8 — Pilot 1–2 quy trình

- Triển khai BnK IDP + RPA.
- Tích hợp ERP và DMS.
- Thiết lập kiểm soát ngoại lệ.
- Đào tạo đội vận hành.
- Chạy song song với quy trình hiện tại.

### Tuần 9–12 — Nghiệm thu và mở rộng

- So sánh kết quả với baseline.
- Nghiệm thu.
- Chuyển giao vận hành.
- Hoàn thiện quản trị và tuân thủ.
- Xây dựng lộ trình mở rộng sang các quy trình còn lại.

---

## 14. Kết luận

Đề xuất của BnK tập trung vào việc tự động hóa xuyên suốt tài chính – kế toán FMCG bằng IDP và RPA, nhưng vẫn giữ con người tại các điểm ra quyết định quan trọng.

Giá trị chính của giải pháp gồm:

- Giảm thao tác nhập liệu và đối chiếu.
- Giảm thời gian xử lý hóa đơn.
- Tăng độ chính xác.
- Rút ngắn chu kỳ đóng sổ.
- Minh bạch công nợ, deductions và trade spend.
- Theo dõi dòng tiền gần thời gian thực.
- Tăng khả năng kiểm toán và tuân thủ.
- Không phải thay thế toàn bộ hệ thống hiện có.

**Bước tiếp theo được đề xuất:** phê duyệt pilot 90 ngày trên 1–2 quy trình ưu tiên để kiểm chứng hiệu quả bằng dữ liệu thực tế trước khi mở rộng toàn doanh nghiệp.
