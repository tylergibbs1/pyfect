- Percent-encoding a URL or a form body (`http_request.body_url_params`, `url_params`, URL
  setters) runs in two passes in C instead of a loop per character: a 40,000 character Slack
  message body encodes about three times faster.
