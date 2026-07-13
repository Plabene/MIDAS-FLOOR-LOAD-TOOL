from app.core.mgt_parser import parse_elastic_links_from_text


def test_parse_elastic_links_accepts_section_name_variants_and_continuation():
    text = """
*ELASTICLINK
   1, GENERAL, 100, 200
*ELASTIC-LINKS
   2, RIGID, 101, 201
*ELASTIC LINK
   3, GENERAL, 102, \\
      202, 0
*ELASTIC-LINK
   4, 103, 203
*ENDDATA
"""

    links = parse_elastic_links_from_text(text)

    assert [(link.link_id, link.node_i, link.node_j) for link in links] == [
        (1, 100, 200),
        (2, 101, 201),
        (3, 102, 202),
        (4, 103, 203),
    ]
