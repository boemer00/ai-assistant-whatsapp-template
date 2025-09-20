from app.utils.twilio import escape_for_xml, to_twiml_message, XML_DECL


def test_escape_for_xml():
    original = "<&>\"'"
    escaped = escape_for_xml(original)
    assert escaped == "&lt;&amp;&gt;&quot;&apos;"


def test_to_twiml_message_structure():
    xml = to_twiml_message("Hello & <world>")
    assert xml.startswith(XML_DECL)
    assert "<Response><Message>" in xml
    assert "Hello &amp; &lt;world&gt;" in xml
    assert xml.endswith("</Message></Response>")
