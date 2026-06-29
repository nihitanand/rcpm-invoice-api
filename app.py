from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import io, base64, os, tempfile

app = Flask(__name__)
CORS(app)  # Allow calls from Netlify

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "RCPM Invoice API running", "version": "1.2"})

@app.route("/invoice", methods=["POST", "OPTIONS"])
def invoice():
    if request.method == "OPTIONS":
        return "", 200
    try:
        data = request.get_json()
        pdf_bytes = generate_invoice(data)
        buf = io.BytesIO(pdf_bytes)
        buf.seek(0)
        inv_no = data.get("inv_no","RCPM-Invoice").replace("/","-")
        return send_file(buf, mimetype="application/pdf",
                         as_attachment=False,
                         download_name=f"{inv_no}.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_invoice(d):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Table, TableStyle, HRFlowable,
                                     Image as RLImage)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import qrcode, io as sysio, math, base64 as b64lib
    from reportlab.platypus import Flowable

    # Register Unicode font
    for path, name in [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      "DJV"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DJVB"),
    ]:
        if os.path.exists(path):
            try: pdfmetrics.registerFont(TTFont(name, path))
            except: pass

    registered = pdfmetrics.getRegisteredFontNames()
    FN  = "DJV"  if "DJV"  in registered else "Helvetica"
    FNB = "DJVB" if "DJVB" in registered else "Helvetica-Bold"

    # Colors
    NAVY      = colors.HexColor("#1B3A6B")
    BLACK     = colors.HexColor("#111111")
    DKGRAY    = colors.HexColor("#444444")
    WHITE     = colors.white
    LGOLD     = colors.HexColor("#FDF3DC")
    GOLD_LINE = colors.HexColor("#C9A84C")
    LGRAY     = colors.HexColor("#F5F5F5")
    MGRAY     = colors.HexColor("#CCCCCC")

    W, H = A4
    LM = RM = 18*mm
    CW = W - LM - RM

    def PS(tag, sz=9, col=BLACK, fn=None, align=TA_LEFT, ld=None, **kw):
        return ParagraphStyle(tag, fontSize=sz, textColor=col,
                              fontName=fn or FN, alignment=align,
                              leading=ld or max(sz*1.35,11), **kw)
    def PB(tag, sz=9, col=BLACK, align=TA_LEFT, ld=None, **kw):
        return ParagraphStyle(tag, fontSize=sz, textColor=col,
                              fontName=FNB, alignment=align,
                              leading=ld or max(sz*1.35,11), **kw)
    def R(n): return f"₹{n:,}"

    # Gear Flowable
    class RotaryGear(Flowable):
        def __init__(self, size=20*mm, color=GOLD_LINE):
            super().__init__()
            self.size = size; self.color = color
            self.width = size; self.height = size
        def draw(self):
            c=self.canv; sz=self.size; cx=cy=sz/2
            R_=sz/2*0.95; teeth=24
            r_out=R_; r_in=R_*0.78; r_hub=R_*0.30
            r_hole=R_*0.17; sp_w=R_*0.09
            pts=[]
            for i in range(teeth*2):
                a=2*math.pi*i/(teeth*2)-math.pi/2
                rad=r_out if i%2==0 else r_in
                pts+=[cx+rad*math.cos(a), cy+rad*math.sin(a)]
            c.setFillColor(self.color)
            path=c.beginPath()
            path.moveTo(pts[0],pts[1])
            for i in range(2,len(pts),2): path.lineTo(pts[i],pts[i+1])
            path.close(); c.drawPath(path,fill=1,stroke=0)
            c.setFillColor(WHITE)
            for i in range(6):
                a=math.pi*i/3
                x1=cx+r_hub*math.cos(a); y1=cy+r_hub*math.sin(a)
                x2=cx+r_in*math.cos(a);  y2=cy+r_in*math.sin(a)
                px=-math.sin(a)*sp_w*0.5; py=math.cos(a)*sp_w*0.5
                p2=c.beginPath()
                p2.moveTo(x1+px,y1+py); p2.lineTo(x2+px,y2+py)
                p2.lineTo(x2-px,y2-py); p2.lineTo(x1-px,y1-py)
                p2.close(); c.drawPath(p2,fill=1,stroke=0)
            c.setFillColor(self.color); c.circle(cx,cy,r_hub,fill=1,stroke=0)
            c.setFillColor(WHITE);      c.circle(cx,cy,r_hole,fill=1,stroke=0)

    # QR
    def make_qr(upi, name, amount, ref):
        url=(f"upi://pay?pa={upi}&pn={name.replace(' ','%20')}"
             f"&am={amount}&cu=INR&tn={ref}")
        q=qrcode.QRCode(version=2,box_size=6,border=2,
                         error_correction=qrcode.constants.ERROR_CORRECT_M)
        q.add_data(url); q.make(fit=True)
        img=q.make_image(fill_color="#1B3A6B",back_color="white")
        buf=sysio.BytesIO(); img.save(buf,"PNG"); buf.seek(0)
        return buf

    # Logo paths — relative to this file's location
    _dir = os.path.dirname(os.path.abspath(__file__))
    rot_logo_path = os.path.join(_dir, "logos", "rotary.png")
    cli_logo_path = os.path.join(_dir, "logos", "cli.png")

    # Extract params
    inv_no   = d.get("inv_no","RCPM/2026-27/001")
    inv_date = d.get("inv_date","01 July 2026")
    primary  = d.get("primary","Rtn. Member")
    spouse   = d.get("spouse","")
    mtype    = d.get("mtype","couple")
    period   = d.get("period","Jul 2026 – Jun 2027")
    ry       = d.get("ry","2026–27")
    ri_pres  = d.get("ri_president","Rtn. Olayinka Hakeem Babalola")
    dg       = d.get("dg","Rtn. Anu Narang")
    pres     = d.get("president","Rtn. Rajesh Agarwal")
    secy     = d.get("secretary","Rtn. Vishal Bijpuria")
    treas    = d.get("treasurer","Rtn. Chintaan Jain")
    r_pri    = int(d.get("rate_primary",30000))
    r_sp     = int(d.get("rate_spouse",10000))
    r_erey   = int(d.get("rate_erey",2500))
    bank     = d.get("bank","Federal Bank")
    acc_nm   = d.get("acc_name","Rotary Club of Patna Millennium")
    acc_no   = d.get("acc_no","12200200026542")
    ifsc     = d.get("ifsc","FDRL0001220")
    upi      = d.get("upi","rotary26542@fbl")
    pan      = d.get("pan","AAABR8354E")
    formation= d.get("formation","12/05/2023")
    addr1    = d.get("addr1","Athak Awas, 115-A, Gandhi Nagar West")
    addr2    = d.get("addr2","Boring Canal Road, Patna \u2013 800001")
    club_no  = d.get("club_no","225235")
    district = d.get("district","3250")

    couple = (mtype=="couple")
    erey_total = r_erey*(2 if couple else 1)
    total  = r_pri + (r_sp if couple else 0) + erey_total
    mbr    = f"{primary} & {spouse}" if couple else primary

    buf = sysio.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
          leftMargin=LM, rightMargin=RM,
          topMargin=10*mm, bottomMargin=8*mm)
    S = []

    # 1. TOP DETACH BAR
    tb = Table([[
        Paragraph("DETACH BELOW AND RETURN WITH PAYMENT", PS("d1",7,WHITE,FNB,TA_LEFT)),
        Paragraph("PAYMENT DUE UPON RECEIPT",             PS("d2",7,WHITE,FNB,TA_RIGHT)),
    ]], colWidths=[CW*0.6,CW*0.4], rowHeights=[11])
    tb.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),NAVY),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
        ('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
    ]))
    S.append(tb); S.append(Spacer(1,5))

    # 2. LOGO HEADER
    LH = 22*mm
    logo_rot = RLImage(rot_logo_path, width=60*mm, height=LH)
    logo_cli = RLImage(cli_logo_path, width=38*mm, height=LH)
    amt_box = Table([
        [Paragraph("PAYMENT DUE UPON RECEIPT", PB("pd",7,NAVY,TA_CENTER))],
        [Paragraph(R(total), PB("amt",19,NAVY,TA_CENTER,ld=23))],
    ], colWidths=[46*mm])
    amt_box.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),1.5,NAVY),
        ('LINEBELOW',(0,0),(-1,0),0.5,NAVY),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
    ]))
    gap=CW-60*mm-38*mm-46*mm-6*mm
    hdr=Table([[logo_rot,Spacer(gap,1),logo_cli,Spacer(6,1),amt_box]],
              colWidths=[60*mm,gap,38*mm,6*mm,46*mm],rowHeights=[LH])
    hdr.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    S.append(hdr); S.append(Spacer(1,4))
    S.append(HRFlowable(width=CW,thickness=2.5,color=NAVY,spaceAfter=0))
    S.append(HRFlowable(width=CW,thickness=2.5,color=GOLD_LINE,spaceAfter=5))

    # 3. CLUB TITLE
    S.append(Paragraph("ROTARY CLUB OF PATNA MILLENNIUM",
        PB("cn",15,NAVY,TA_CENTER,ld=18,spaceAfter=1)))
    S.append(Paragraph(f"Club No. {club_no}  |  R.I. District {district}",
        PB("cs",9,BLACK,TA_CENTER,spaceAfter=1)))
    S.append(Paragraph(addr1, PS("a1",8,DKGRAY,FN,TA_CENTER,spaceAfter=0)))
    S.append(Paragraph(addr2, PS("a2",8,DKGRAY,FN,TA_CENTER,spaceAfter=4)))
    S.append(HRFlowable(width=CW,thickness=0.4,color=MGRAY,spaceAfter=4))

    # Meta
    MC=[CW*0.19,CW*0.295,CW*0.03,CW*0.205,CW*0.28]
    meta=Table([
        [Paragraph("INVOICE NUMBER",PB("mk1",8,NAVY)),Paragraph(inv_no,PS("mv1",8,BLACK)),"",
         Paragraph("INVOICE DATE",PB("mk2",8,NAVY)),Paragraph(inv_date,PS("mv2",8,BLACK))],
        [Paragraph("CLUB NAME",PB("mk3",8,NAVY)),Paragraph("Patna Millennium",PS("mv3",8,BLACK)),"",
         Paragraph("CLUB NUMBER",PB("mk4",8,NAVY)),Paragraph(club_no,PS("mv4",8,BLACK))],
        [Paragraph("DISTRICT",PB("mk5",8,NAVY)),Paragraph(district,PS("mv5",8,BLACK)),"",
         Paragraph("MEMBERSHIP TYPE",PB("mk6",8,NAVY)),
         Paragraph("Couple" if couple else "Single",PS("mv6",8,BLACK))],
    ], colWidths=MC)
    meta.setStyle(TableStyle([
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))
    S.append(meta); S.append(Spacer(1,5))
    S.append(HRFlowable(width=CW,thickness=0.5,color=MGRAY,spaceAfter=5))

    # 4. BILLED TO | OFFICE BEARERS
    half=CW/2-3
    bi=Table([
        [Paragraph("BILLED TO",PB("btl",7.5,BLACK))],
        [Paragraph(mbr,PB("bn",11,NAVY,ld=15))],
        [Paragraph("Rotary Club of Patna Millennium",PS("bs",8.5,DKGRAY))],
        [Paragraph(f"Billing Period: {period}",PS("bp",8,DKGRAY))],
    ], colWidths=[half])
    bi.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGOLD),('BOX',(0,0),(-1,-1),0.5,GOLD_LINE),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
    ]))
    ob=Table([
        [Paragraph("OFFICE BEARERS 2026–27",PB("obl",7.5,BLACK))],
        [Paragraph(f"RI President   :  {ri_pres}",PB("ob1",8,BLACK,ld=12))],
        [Paragraph(f"Dist. Governor :  {dg}",PB("ob2",8,BLACK,ld=12))],
        [Paragraph(f"Club President :  {pres}",PB("ob3",8,NAVY,ld=12))],
        [Paragraph(f"Club Secretary :  {secy}",PB("ob4",8,NAVY,ld=12))],
        [Paragraph(f"Club Treasurer :  {treas}",PB("ob5",8,NAVY,ld=12))],
    ], colWidths=[half])
    ob.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGRAY),('BOX',(0,0),(-1,-1),0.5,MGRAY),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
    ]))
    sec4=Table([[bi,Spacer(6,1),ob]],colWidths=[half,6,half])
    sec4.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    S.append(sec4); S.append(Spacer(1,7))

    # 5. DUES TABLE
    DC=[CW*0.365,CW*0.265,CW*0.09,CW*0.14,CW*0.14]
    def tH(t): return Paragraph(t,PB("th"+t[:4],8,WHITE,TA_CENTER,ld=10))
    def tL(t): return Paragraph(t,PS("tl"+t[:4],9,DKGRAY,ld=11))
    def tN(t): return Paragraph(t,PS("tn"+t[:4],9,DKGRAY,FN,TA_CENTER,ld=11))
    def tRv(t): return Paragraph(t,PB("tr"+t[:4],9,BLACK,TA_RIGHT,ld=11))

    rows=[[tH("DESCRIPTION"),tH("PERIOD"),tH("QTY"),tH("UNIT PRICE"),tH("TOTAL")]]
    rows.append([tL("Primary Membership Dues"),tL(period),tN("1"),tRv(R(r_pri)),tRv(R(r_pri))])
    if couple:
        rows.append([tL("Spouse / Associate Member Dues"),tL(period),tN("1"),tRv(R(r_sp)),tRv(R(r_sp))])
    rows.append([tL("Every Rotarian Every Year (EREY)"),tL(period),
                 tN("2" if couple else "1"),tRv(R(r_erey)),tRv(R(erey_total))])

    dues=Table(rows,colWidths=DC)
    dues.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,LGRAY]),
        ('BOX',(0,0),(-1,-1),0.5,NAVY),
        ('INNERGRID',(0,0),(-1,-1),0.3,MGRAY),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
    ]))
    S.append(dues)

    # Summary rows
    prev=Table([[
        Paragraph("PREVIOUS BALANCE",PB("pb",8.5,DKGRAY,TA_RIGHT,ld=12)),
        Paragraph("0.00",PS("pv",8.5,DKGRAY,FN,TA_RIGHT,ld=12)),
    ]],colWidths=[DC[0]+DC[1]+DC[2]+DC[3],DC[4]],rowHeights=[18])
    prev.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGRAY),
        ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('BOX',(0,0),(-1,-1),0.3,MGRAY),
    ]))
    tot_row=Table([[
        Paragraph("TOTAL CLUB BALANCE (INR)",PB("tl",9,NAVY,TA_RIGHT,ld=13)),
        Paragraph(R(total),PB("tv",10,NAVY,TA_RIGHT,ld=13)),
    ]],colWidths=[DC[0]+DC[1]+DC[2]+DC[3],DC[4]],rowHeights=[22])
    tot_row.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGOLD),
        ('LINEABOVE',(0,0),(-1,-1),1.5,GOLD_LINE),
        ('LINEBELOW',(0,0),(-1,-1),2,NAVY),
        ('BOX',(0,0),(-1,-1),0.5,NAVY),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))
    S.append(prev); S.append(tot_row); S.append(Spacer(1,9))

    # 6. PAYMENT SECTION
    tax_w=30*mm; gap2=4; qr_w=38*mm
    pd_w=CW-tax_w-qr_w-gap2*2

    qr_buf=make_qr(upi,acc_nm,total,inv_no)
    qr_img=RLImage(qr_buf,width=qr_w-4,height=qr_w-4)
    TP=2; LP=7

    bank_tbl=Table([
        [Paragraph("PAYMENT METHODS",PB("pm",8,WHITE,TA_LEFT))],
        [Paragraph(f"Account Name :  {acc_nm}",PS("p1",8,DKGRAY))],
        [Paragraph(f"Bank Name    :  {bank}",PS("p2",8,DKGRAY))],
        [Paragraph(f"Account No   :  {acc_no}",PB("p3",8,NAVY))],
        [Paragraph(f"IFSC Code    :  {ifsc}",PS("p4",8,DKGRAY))],
        [Paragraph(f"UPI ID       :  {upi}  (Scan QR \u2192)",PB("p5",8,NAVY))],
        [Paragraph(f"Ref: {inv_no} in payment remarks.",PS("p6",7.5,DKGRAY))],
    ],colWidths=[pd_w])
    bank_tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('BACKGROUND',(0,1),(-1,-1),LGRAY),
        ('TOPPADDING',(0,0),(-1,-1),TP),('BOTTOMPADDING',(0,0),(-1,-1),TP),
        ('LEFTPADDING',(0,0),(-1,-1),LP),('RIGHTPADDING',(0,0),(-1,-1),LP),
        ('TOPPADDING',(0,0),(-1,0),4),('BOTTOMPADDING',(0,0),(-1,0),4),
    ]))
    tax_tbl=Table([
        [Paragraph("TAX INFORMATION",PB("tx0",8,WHITE))],
        [Paragraph("PAN",PB("tx1",7.5,NAVY))],
        [Paragraph(pan,PB("tx2",8,BLACK))],
        [Paragraph("Formation Date",PB("tx3",7.5,NAVY))],
        [Paragraph(formation,PS("tx4",8,BLACK))],
        [Paragraph("",PS("tx5",4,BLACK))],
        [Paragraph("",PS("tx6",4,BLACK))],
    ],colWidths=[tax_w])
    tax_tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),NAVY),
        ('BACKGROUND',(0,1),(-1,-1),LGRAY),
        ('LINEBELOW',(0,1),(-1,2),0.3,MGRAY),
        ('LINEBELOW',(0,3),(-1,4),0.3,MGRAY),
        ('TOPPADDING',(0,0),(-1,-1),TP),('BOTTOMPADDING',(0,0),(-1,-1),TP),
        ('LEFTPADDING',(0,0),(-1,-1),LP),('RIGHTPADDING',(0,0),(-1,-1),LP),
        ('TOPPADDING',(0,0),(-1,0),4),('BOTTOMPADDING',(0,0),(-1,0),4),
    ]))
    qr_tbl=Table([[qr_img],[Paragraph("Scan to Pay",PB("ql",7,NAVY,TA_CENTER))]],
                 colWidths=[qr_w])
    qr_tbl.setStyle(TableStyle([
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('BACKGROUND',(0,0),(-1,-1),WHITE),
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
    ]))

    pay_row=Table([[bank_tbl,tax_tbl,qr_tbl]],
                  colWidths=[pd_w+gap2,tax_w+gap2,qr_w])
    pay_row.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
        ('BOX',(0,0),(-1,-1),1,GOLD_LINE),
        ('LINEAFTER',(0,0),(0,-1),0.5,GOLD_LINE),
        ('LINEAFTER',(1,0),(1,-1),0.5,GOLD_LINE),
        ('BACKGROUND',(0,0),(0,0),LGRAY),
        ('BACKGROUND',(1,0),(1,0),LGRAY),
        ('BACKGROUND',(2,0),(2,0),WHITE),
    ]))
    S.append(pay_row); S.append(Spacer(1,7))

    # 7. NOTIFICATIONS
    notif=Table([
        [Paragraph("NOTIFICATIONS",PB("nl",8,NAVY))],
        [Paragraph("Please mention club name, club number, and invoice number on back of cheque / demand draft.",PS("n1",7.5,DKGRAY,ld=10))],
        [Paragraph("Account number is club-specific. Do not share. Electronic payment preferred.",PS("n2",7.5,DKGRAY,ld=10))],
        [Paragraph("Computer-generated invoice. For queries contact the Club Treasurer.",PS("n3",7.5,DKGRAY,ld=10))],
    ],colWidths=[CW])
    notif.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5,MGRAY),
        ('LINEBELOW',(0,0),(-1,0),0.5,MGRAY),
        ('BACKGROUND',(0,0),(-1,0),LGRAY),
        ('BACKGROUND',(0,1),(-1,-1),WHITE),
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
        ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
    ]))
    S.append(notif); S.append(Spacer(1,7))

    # 8. FOOTER
    S.append(HRFlowable(width=CW,thickness=2.5,color=NAVY,spaceAfter=0))
    S.append(HRFlowable(width=CW,thickness=2.5,color=GOLD_LINE,spaceAfter=5))
    sig=Table([
        [Paragraph(pres,PB("s1",8.5,NAVY,TA_CENTER)),
         Paragraph(secy,PB("s2",8.5,NAVY,TA_CENTER)),
         Paragraph(treas,PB("s3",8.5,NAVY,TA_CENTER))],
        [Paragraph("President",PS("r1",8,BLACK,FN,TA_CENTER)),
         Paragraph("Secretary",PS("r2",8,BLACK,FN,TA_CENTER)),
         Paragraph("Treasurer",PS("r3",8,BLACK,FN,TA_CENTER))],
    ],colWidths=[CW/3]*3,rowHeights=[14,12])
    sig.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),LGOLD),
        ('ALIGN',(0,0),(-1,-1),'CENTER'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('INNERGRID',(0,0),(-1,-1),0.3,GOLD_LINE),
        ('BOX',(0,0),(-1,-1),0.5,GOLD_LINE),
        ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
    ]))
    S.append(sig); S.append(Spacer(1,4))
    S.append(Paragraph(
        f"Rotary Club of Patna Millennium  ·  Club No. {club_no}  ·  "
        f"R.I. District {district}  ·  Service Above Self",
        PS("ft",7.5,MGRAY,FN,TA_CENTER)))
    S.append(Spacer(1,3))
    bot=Table([[""]],colWidths=[CW],rowHeights=[4])
    bot.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),GOLD_LINE)]))
    S.append(bot)

    doc.build(S)
    return buf.getvalue()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
