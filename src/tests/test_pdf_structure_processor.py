from my_app.pdf_processor import StructureProcessor

XML = """
<TEI>
  <text>
    <p coords="1,10,20,30,40;2,15,25,35,45;">Paragraph</p>
    <head coords="2,50,60,70,80">Heading</head>
  </text>
  <surface ulx="0" uly="0" lrx="612" lry="792" />
  <surface ulx="10" uly="20" lrx="210" lry="320" />
</TEI>
"""


def test_get_pages_returns_width_and_height_for_each_surface():
    processor = StructureProcessor(XML)

    assert processor.get_pages() == [
        {"width": 612.0, "height": 792.0},
        {"width": 200.0, "height": 300.0},
    ]


def test_get_coordinates_returns_one_entry_per_box_with_metadata():
    processor = StructureProcessor(XML)

    assert processor.get_coordinates() == [
        {
            "page": "1",
            "x": "10",
            "y": "20",
            "width": "30",
            "height": "40",
            "color": "rgba(139, 0, 0, 0.4)",
            "type": "p",
            "text": "Paragraph",
        },
        {
            "page": "2",
            "x": "15",
            "y": "25",
            "width": "35",
            "height": "45",
            "color": "rgba(139, 0, 0, 0.4)",
            "type": "p",
            "text": "Paragraph",
        },
        {
            "page": "2",
            "x": "50",
            "y": "60",
            "width": "70",
            "height": "80",
            "color": "rgba(139, 139, 0, 1)",
            "type": "head",
            "text": "Heading",
        },
    ]
