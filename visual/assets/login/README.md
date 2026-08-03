# Login and lock concept

Authentication remains upstream GDM. This concept specifies Bunny identity
around, not inside, the authentication mechanism. It retains user selection,
password visibility, keyboard layout, accessibility, network, power, error
announcements, and the session selector. The selector must expose upstream
GNOME and the additive `Bunny Visual Preview` entry.

The visual package never patches credential handling, removes GNOME, selects a
default user/session, or stores authentication material. High contrast, large
text, and screen-reader activation remain available before authentication.
