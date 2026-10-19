# -*- coding: utf-8 -*-
"""원문 전체 자료화 — 문서 목록(build_fulltext.py가 읽음).

file: 올린 원본 폴더 안 파일 이름의 앞 8자리(업로드 접두). 원본은 고치지 않고 작업 폴더로 복사해 읽는다.
ed: 판 이름(시행일 YYYY-MM-DD). 판이 여럿이면 현행·예정 + 직전 1판만 둔다.
fmt: law(국가법령정보센터 PDF) | pdfpage(쪽 단위) | hwpx(장·절) | hwp(고시)
"""

LAW = '국가법령정보센터'
LAWURL = 'https://www.law.go.kr/법령/'
ORDURL = 'https://www.law.go.kr/자치법규/'
LAW_NOTICE = '법령·자치법규 원문은 저작권 보호 대상이 아님(저작권법 제7조). 국가법령정보센터 출력본에서 추출.'


def law(docid, title, publisher, eds, group='법령', kind='법령', parent=None, dec=None, url=None):
    return dict(docid=docid, title=title, kind=kind, group=group, publisher=publisher, kogl='비보호',
                notice=LAW_NOTICE, source_url=url or LAWURL + title.replace(' ', ''), fmt='law', editions=eds,
                parent=parent, dec=dec)


def E(ed, file, prom=None, hint=None, **kw):
    d = dict(ed=ed, file=file, promulgated=prom, effective=ed, status_hint=hint)
    d.update(kw)
    return d


DOCS = [
    # 아동
    law('child-act', '아동복지법', '보건복지부', [E('2026-10-02', 'b76b3639', '2026-09-29')]),
    law('child-dec', '아동복지법 시행령', '보건복지부', [E('2026-08-04', '55180171', '2026-08-04'), E('2027-01-01', 'd47514a0', '2026-08-04', '예정')], parent='child-act'),
    law('child-rule', '아동복지법 시행규칙', '보건복지부', [E('2026-10-02', '1107de96', '2026-10-02')], parent='child-act', dec='child-dec'),
    law('abuse-act', '아동학대범죄의 처벌 등에 관한 특례법', '법무부·보건복지부', [E('2026-10-02', '28fb78b4')]),
    law('abuse-dec', '아동학대범죄의 처벌 등에 관한 특례법 시행령', '법무부·보건복지부', [E('2026-10-02', 'c3f39a65')], parent='abuse-act'),
    law('abuse-rule', '아동학대범죄의 처벌 등에 관한 특례법 시행규칙', '법무부·보건복지부', [E('2026-10-02', '1d0d75ce')], parent='abuse-act', dec='abuse-dec'),
    # 사회복지
    law('welfare-act', '사회복지사업법', '보건복지부', [E('2025-10-02', '811a1367', '2025-04-01')]),
    law('welfare-dec', '사회복지사업법 시행령', '보건복지부', [E('2026-02-03', 'f7ff4a10', '2026-02-03')], parent='welfare-act'),
    law('welfare-rule', '사회복지사업법 시행규칙', '보건복지부', [E('2026-08-27', '1c430859', '2026-08-27')], parent='welfare-act', dec='welfare-dec'),
    law('fin-rule', '사회복지법인 및 사회복지시설 재무ㆍ회계 규칙', '보건복지부', [E('2023-01-01', 'd080b5c6')], parent='welfare-act'),
    # 노동·개인정보
    law('labor-act', '근로기준법', '고용노동부', [E('2026-10-08', '5746af85', '2026-04-07'), E('2027-06-10', '275391e1', '2026-06-09', '예정')]),
    law('labor-dec', '근로기준법 시행령', '고용노동부', [E('2025-10-23', '8cd40dd4', '2025-04-08')], parent='labor-act'),
    law('labor-rule', '근로기준법 시행규칙', '고용노동부', [E('2025-02-23', 'f272d362', '2025-02-21')], parent='labor-act', dec='labor-dec'),
    law('privacy-act', '개인정보 보호법', '개인정보보호위원회', [E('2026-09-11', '5f83e6b3', '2026-03-10'), E('2027-03-09', 'f536b74c', '2026-09-08', '예정'), E('2027-07-01', '5824c3f7', '2026-03-10', '예정')]),
    law('privacy-dec', '개인정보 보호법 시행령', '개인정보보호위원회', [E('2026-09-11', 'a82c576f', '2026-09-10')], parent='privacy-act'),
    # 지방 계약·보조금
    law('lcontract-act', '지방자치단체를 당사자로 하는 계약에 관한 법률', '행정안전부', [E('2024-02-17', '2a4ceeb4')]),
    law('lcontract-dec', '지방자치단체를 당사자로 하는 계약에 관한 법률 시행령', '행정안전부', [E('2026-06-03', '742e26ea')], parent='lcontract-act'),
    law('lcontract-rule', '지방자치단체를 당사자로 하는 계약에 관한 법률 시행규칙', '행정안전부', [E('2026-07-01', '3f906e99'), E('2026-10-25', '97e9a820', '2026-04-24', '예정')], parent='lcontract-act', dec='lcontract-dec'),
    law('lsubsidy-act', '지방자치단체 보조금 관리에 관한 법률', '행정안전부', [E('2023-10-12', '314f2670')]),
    law('lsubsidy-dec', '지방자치단체 보조금 관리에 관한 법률 시행령', '행정안전부', [E('2023-10-12', '90afa2e9')], parent='lsubsidy-act'),
    law('lsubsidy-rule', '지방자치단체 보조금 관리에 관한 법률 시행규칙', '행정안전부', [E('2023-12-13', 'e1290339')], parent='lsubsidy-act', dec='lsubsidy-dec'),
    # 행정업무·가족관계
    law('admin-dec', '행정업무의 운영 및 혁신에 관한 규정', '행정안전부', [E('2026-10-02', '6744430c')]),
    law('admin-rule', '행정업무의 운영 및 혁신에 관한 규정 시행규칙', '행정안전부', [E('2023-06-28', 'a805da24')], parent='admin-dec'),
    law('family-rule', '가족관계의 등록 등에 관한 규칙', '대법원', [E('2025-07-19', '15ee2cac', '2025-06-26', extra=['8ce9fe39'])]),
    # 조례
    law('cb-subsidy-ord', '충청북도 지방보조금 관리 조례', '충청북도', [E('2025-05-16', 'acf35a0b', '2025-05-16')], group='조례', kind='조례',
        url=ORDURL + '충청북도지방보조금관리조례'),
    law('jc-subsidy-ord', '제천시 지방보조금 관리 조례', '충청북도 제천시', [E('2021-07-30', 'bc087106', '2021-07-30')], group='조례', kind='조례',
        url=ORDURL + '제천시지방보조금관리조례'),
]


def guide(docid, title, publisher, eds, kogl, notice, fmt='pdfpage', group='지침', kind='지침', url=''):
    return dict(docid=docid, title=title, kind=kind, group=group, publisher=publisher, kogl=kogl, notice=notice,
                source_url=url, fmt=fmt, editions=eds)


MOHW = 'https://www.mohw.go.kr'
DOCS += [
    guide('guide-child1', '2026 아동분야 사업안내 1권', '보건복지부',
          [E('2026-07-01', '63baba7e', fmt='hwpx', label='2026. 7. 개정본(HWPX)'), E('2026-03-19', '92dc9da1', label='2026. 3. 발간본(PDF, 표지 표기 2025)')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 발간 지침(법령 아님).', url=MOHW),
    guide('guide-child2', '2026 아동분야 사업안내 2권', '보건복지부',
          [E('2026-07-01', '03f32278', fmt='hwpx', label='2026. 7. 개정본(HWPX)'), E('2026-03-19', 'ea234c92', label='2026. 3. 발간본(PDF, 표지 표기 2025)')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 발간 지침(법령 아님).', url=MOHW),
    guide('guide-facility', '2026 사회복지시설 관리안내', '보건복지부', [E('2026-01-01', '605c690c')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 발간 지침(법령 아님).', url=MOHW),
    guide('guide-corp', '2026 사회복지법인 관리안내', '보건복지부', [E('2026-01-01', '4a556c50')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 발간 지침(법령 아님).', url=MOHW),
    guide('selfrel1', '2026 자립지원 업무 매뉴얼 Ⅰ', '보건복지부·아동권리보장원', [E('2026-01-01', 'aef6330e')],
          '표시 없음', '원문에 공공누리 표시 없음. 업무 매뉴얼(법령 아님).'),
    guide('selfrel2', '2026 자립지원 업무 매뉴얼 Ⅱ', '보건복지부·아동권리보장원', [E('2026-01-01', 'd88a3b4e')],
          '표시 없음', '원문에 공공누리 표시 없음. 업무 매뉴얼(법령 아님).'),
    guide('wage-guide', '2026년 사회복지시설 종사자 인건비 가이드라인', '보건복지부', [E('2026-01-01', '186f3a1a')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 가이드라인(법령 아님).', url=MOHW),
    guide('inspect-cases-2024', '2024 사회복지법인·시설 현지조사 절차 및 사례집', '보건복지부', [E('2024-12-01', '0c6c69e2')],
          '표시 없음', '원문에 공공누리 표시 없음. 보건복지부 발간 사례집(법령 아님).', url=MOHW),
    guide('inspect-manual-2023', '2023 사회복지법인·시설 현지조사 매뉴얼', '보건복지부', [E('2023-01-01', '9c701e84')],
          '표시 없음', '원문 표기: “본 매뉴얼은 보건복지부(복지급여조사담당관)의 사회복지법인 및 시설에 대한 현지조사 방식을 소개한 것으로 담당 공무원의 체계적인 조사업무 습득을 지원하기 위한 안내서 입니다.” 공무원용 안내서(법령 아님), 개인 사용.', url=MOHW),
    guide('inspect-seoul-2025', '2025 사회복지법인·시설 운영개선을 위한 지도점검사례집', '서울시사회복지협의회', [E('2025-12-01', '55751232')],
          '표시 없음', '원문에 공공누리 표시 없음(발간번호 서사협-25-132). 사례집(법령 아님).'),
    guide('admin-manual', '2025 행정업무운영 편람', '행정안전부', [E('2025-12-17', 'ac0d083b', fmt='hwpx', pdf='d6daf676')],
          '표시 없음', '원문에 공공누리 표시 없음. 원문 표기: “본 책자의 내용은 행정안전부 인터넷 누리집(www.mois.go.kr)의 ‘정책자료’ → ‘간행물’에 게시되어 있으니 많은 활용 바랍니다.” 행정안전부 편람(법령 아님). 쪽은 같은 판 PDF(최종본 2025. 12. 17.)에서 맞춤.'),
    # 어문 규범(개인 사용)
    guide('eomun-spell-std', '한글 맞춤법·표준어 규정 해설', '국립국어원', [E('2018-01-08', 'dd5dc2c6')], '표시 없음',
          '원문 표기: 발행일 2018년 12월 21일, 발행인 국립국어원장, 발행처 국립국어원(발간 등록 번호 11-1371028-000712-01). 공공누리 표시 없음. 개인 사용.', group='어문', kind='어문'),
    guide('eomun-punct', '문장 부호 해설', '국립국어원', [E('2014-12-05', 'fdf137a2')], '표시 없음',
          '원문 표기: “이 책의 저작권은 국립국어원에 있습니다. Copyright ⓒ2014 The National Institute of the Korean Language” (발간 등록 번호 11-1371028-000552-01). 개인 사용.', group='어문', kind='어문'),
    guide('eomun-roman', '국어의 로마자 표기법', '문화체육관광부', [E('2014-12-05', '071532af', fmt='hwp')], '비보호',
          '문화체육관광부 고시 제2014-42호. 고시는 저작권 보호 대상이 아님(저작권법 제7조).', group='어문', kind='어문'),
    guide('eomun-loan', '외래어 표기법', '문화체육관광부', [E('2017-03-28', '5c1660e4', fmt='hwp')], '비보호',
          '문화체육관광부 고시 제2017-14호(2017. 3. 28.). 고시는 저작권 보호 대상이 아님(저작권법 제7조).', group='어문', kind='어문'),
]
