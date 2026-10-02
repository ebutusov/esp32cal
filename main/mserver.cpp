#include "mserver.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <sys/stat.h>

#include "esp_http_server.h"
#include "esp_log.h"

#include "str_util.h"

static const char *TAG = "mserver";

static std::string getContentType(const std::string &filename)
{ // convert the file extension to the MIME type
  if (str_ends_with(filename, ".html")) return "text/html";
  else if (str_ends_with(filename, ".css")) return "text/css";
  else if (str_ends_with(filename, ".js")) return "application/javascript";
  else if (str_ends_with(filename, ".ico")) return "image/x-icon";
  else if (str_ends_with(filename, ".gz")) return "application/x-gzip";
  else if (str_ends_with(filename, ".json")) return "application/json";
  return "text/plain";
}

static bool file_exists(const std::string &path)
{
  struct stat st;
  return stat(path.c_str(), &st) == 0;
}

// send the right file to the client (if it exists)
static bool handleFileRead(httpd_req_t *req, std::string path)
{
  ESP_LOGI(TAG, "handleFileRead: %s", path.c_str());
  if (path.empty() || path.back() == '/')
    path += "index.html";                                 // If a folder is requested, send the index file
  std::string contentType = getContentType(path);          // Get the MIME type
  std::string fsPath = "/spiffs" + path;
  std::string fsPathGz = fsPath + ".gz";

  std::string chosen;
  bool gzipped = false;
  if (file_exists(fsPathGz)) {                             // If there's a compressed version available
    chosen = fsPathGz;                                     // Use the compressed version
    gzipped = true;
  } else if (file_exists(fsPath)) {
    chosen = fsPath;
  } else {
    ESP_LOGI(TAG, "\tFile Not Found: %s", path.c_str());   // If the file doesn't exist, return false
    return false;
  }

  FILE *file = fopen(chosen.c_str(), "rb");                // Open the file
  if (!file)
    return false;

  httpd_resp_set_type(req, contentType.c_str());
  if (gzipped)
    httpd_resp_set_hdr(req, "Content-Encoding", "gzip");

  char buf[512];
  size_t n;
  while ((n = fread(buf, 1, sizeof(buf), file)) > 0) {      // Send it to the client
    if (httpd_resp_send_chunk(req, buf, n) != ESP_OK) {
      fclose(file);
      return true;
    }
  }
  fclose(file);                                             // Close the file again
  httpd_resp_send_chunk(req, NULL, 0);
  ESP_LOGI(TAG, "\tSent file: %s", chosen.c_str());
  return true;
}

// -- minimal multipart/form-data parsing -----------------------------------
// esp_http_server has no built-in multipart parser (unlike Arduino's
// WebServer, which auto-parses form posts and file uploads); the
// maintenance-mode config UI posts via FormData, so this reads it by hand.

struct MultipartPart {
  std::string headers;
  std::string body;
};

static std::string get_multipart_boundary(httpd_req_t *req)
{
  char buf[128];
  if (httpd_req_get_hdr_value_str(req, "Content-Type", buf, sizeof(buf)) != ESP_OK)
    return "";
  std::string ct(buf);
  auto pos = ct.find("boundary=");
  if (pos == std::string::npos)
    return "";
  return "--" + ct.substr(pos + strlen("boundary="));
}

static std::string read_request_body(httpd_req_t *req)
{
  std::string body;
  int remaining = req->content_len;
  body.reserve(remaining > 0 ? remaining : 0);
  char buf[512];
  while (remaining > 0) {
    int to_read = remaining < (int)sizeof(buf) ? remaining : (int)sizeof(buf);
    int r = httpd_req_recv(req, buf, to_read);
    if (r <= 0)
      break;
    body.append(buf, r);
    remaining -= r;
  }
  return body;
}

// Advances `cursor` past the part found (if any) and fills `part`. Returns
// false once the closing boundary ("--<boundary>--") is reached.
static bool find_next_part(const std::string &body, const std::string &boundary, size_t &cursor, MultipartPart &part)
{
  size_t b = body.find(boundary, cursor);
  if (b == std::string::npos)
    return false;
  size_t after_boundary = b + boundary.size();
  if (body.compare(after_boundary, 2, "--") == 0)
    return false; // closing boundary

  size_t hdr_start = after_boundary;
  if (body.compare(hdr_start, 2, "\r\n") == 0)
    hdr_start += 2;

  size_t hdr_end = body.find("\r\n\r\n", hdr_start);
  size_t next_b = body.find(boundary, hdr_start);
  if (hdr_end == std::string::npos || next_b == std::string::npos || hdr_end > next_b)
    return false;

  part.headers = body.substr(hdr_start, hdr_end - hdr_start);
  size_t value_start = hdr_end + 4;
  size_t value_end = next_b;
  if (value_end >= value_start + 2 && body[value_end - 2] == '\r' && body[value_end - 1] == '\n')
    value_end -= 2;
  part.body = (value_end > value_start) ? body.substr(value_start, value_end - value_start) : std::string();

  cursor = next_b;
  return true;
}

static bool header_field_value(const std::string &headers, const std::string &key, std::string &out)
{
  size_t p = headers.find(key);
  if (p == std::string::npos)
    return false;
  p += key.size();
  size_t e = headers.find('"', p);
  if (e == std::string::npos)
    return false;
  out = headers.substr(p, e - p);
  return true;
}

// ---------------------------------------------------------------------------

static esp_err_t config_post_handler(httpd_req_t *req)
{
  std::string boundary = get_multipart_boundary(req);
  std::string body = read_request_body(req);

  std::string json_data;
  bool found = false;
  if (!boundary.empty()) {
    size_t cursor = 0;
    MultipartPart part;
    while (find_next_part(body, boundary, cursor, part)) {
      std::string name;
      if (header_field_value(part.headers, "name=\"", name) && name == "data") {
        json_data = part.body;
        found = true;
        break;
      }
    }
  }

  if (found) {
    FILE *file = fopen("/spiffs/config.json", "w");
    if (file) {
      fwrite(json_data.data(), 1, json_data.size(), file);
      fclose(file);
    }
    ESP_LOGI(TAG, "Saved config: %s", json_data.c_str());
  } else {
    ESP_LOGW(TAG, "POST /config: no 'data' field found in request body");
  }

  httpd_resp_set_type(req, "text/plain");
  httpd_resp_sendstr(req, "OK");
  return ESP_OK;
}

static esp_err_t upload_post_handler(httpd_req_t *req)
{ // upload a new file to SPIFFS
  std::string boundary = get_multipart_boundary(req);
  std::string body = read_request_body(req);

  if (!boundary.empty()) {
    size_t cursor = 0;
    MultipartPart part;
    while (find_next_part(body, boundary, cursor, part)) {
      std::string filename;
      if (header_field_value(part.headers, "filename=\"", filename) && !filename.empty()) {
        if (filename[0] != '/')
          filename = "/" + filename;
        ESP_LOGI(TAG, "handleFileUpload Name: %s", filename.c_str());
        std::string path = "/spiffs" + filename;
        FILE *file = fopen(path.c_str(), "wb");
        if (!file) {
          httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "500: couldn't create file");
          return ESP_OK;
        }
        fwrite(part.body.data(), 1, part.body.size(), file);
        fclose(file);
        ESP_LOGI(TAG, "handleFileUpload Size: %u", (unsigned)part.body.size());
        httpd_resp_set_status(req, "303 See Other");
        httpd_resp_set_hdr(req, "Location", "/success.html");
        httpd_resp_send(req, NULL, 0);
        return ESP_OK;
      }
    }
  }

  httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "500: couldn't create file");
  return ESP_OK;
}

static esp_err_t upload_get_handler(httpd_req_t *req)
{ // if the client requests the upload page
  if (!handleFileRead(req, "/upload.html")) // send it if it exists
    httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "404: Not Found"); // otherwise, respond with a 404 (Not Found) error
  return ESP_OK;
}

static esp_err_t root_get_handler(httpd_req_t *req)
{ // if the client requests any URI
  std::string uri = req->uri;
  size_t qpos = uri.find('?');
  if (qpos != std::string::npos)
    uri = uri.substr(0, qpos);
  if (!handleFileRead(req, uri)) // send it if it exists
    httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "404: Not Found"); // otherwise, respond with a 404 (Not Found) error
  return ESP_OK;
}

void setupServer()
{
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.uri_match_fn = httpd_uri_match_wildcard;

  httpd_handle_t server = NULL;
  if (httpd_start(&server, &config) != ESP_OK) {
    ESP_LOGE(TAG, "Failed to start http server");
    return;
  }

  httpd_uri_t upload_get = {.uri = "/upload", .method = HTTP_GET, .handler = upload_get_handler, .user_ctx = NULL};
  httpd_register_uri_handler(server, &upload_get);

  httpd_uri_t upload_post = {.uri = "/upload", .method = HTTP_POST, .handler = upload_post_handler, .user_ctx = NULL};
  httpd_register_uri_handler(server, &upload_post);

  httpd_uri_t config_post = {.uri = "/config", .method = HTTP_POST, .handler = config_post_handler, .user_ctx = NULL};
  httpd_register_uri_handler(server, &config_post);

  httpd_uri_t catch_all = {.uri = "/*", .method = HTTP_GET, .handler = root_get_handler, .user_ctx = NULL};
  httpd_register_uri_handler(server, &catch_all);
}
