using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text;

namespace RimLink.Utils
{
    /// <summary>
    /// Легковесный JSON-сериализатор без внешних зависимостей.
    /// Поддерживает: Dictionary, List, анонимные объекты, примитивы.
    /// </summary>
    public static class SimpleJson
    {
        // ── Сериализация ───────────────────────────────────────────────────────

        public static string Serialize(Dictionary<string, object> dict)
            => SerializeObject(dict);

        public static string SerializeList(List<object> list)
            => SerializeObject(list);

        public static string SerializeObject(object obj)
        {
            if (obj == null) return "null";
            if (obj is bool   b) return b ? "true" : "false";
            if (obj is string s) return '"' + Escape(s) + '"';

            if (obj is int || obj is long || obj is short || obj is byte)
                return Convert.ToInt64(obj).ToString();

            if (obj is float || obj is double || obj is decimal)
                return Convert.ToDouble(obj).ToString("G", System.Globalization.CultureInfo.InvariantCulture);

            if (obj is Enum) return Convert.ToInt32(obj).ToString();

            if (obj is Dictionary<string, object> d)
            {
                var sb = new StringBuilder("{");
                bool first = true;
                foreach (var kv in d)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    sb.Append('"').Append(Escape(kv.Key)).Append("\":").Append(SerializeObject(kv.Value));
                }
                return sb.Append('}').ToString();
            }

            if (obj is IList list)
            {
                var sb = new StringBuilder("[");
                bool first = true;
                foreach (var item in list)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    sb.Append(SerializeObject(item));
                }
                return sb.Append(']').ToString();
            }

            // Анонимные объекты и классы через рефлексию
            var type = obj.GetType();
            if (type.IsClass)
            {
                var sb = new StringBuilder("{");
                bool first = true;
                foreach (var prop in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                {
                    if (!first) sb.Append(',');
                    first = false;
                    // camelCase ключ
                    string key = char.ToLowerInvariant(prop.Name[0]) + prop.Name.Substring(1);
                    sb.Append('"').Append(Escape(key)).Append("\":");
                    sb.Append(SerializeObject(prop.GetValue(obj, null)));
                }
                return sb.Append('}').ToString();
            }

            return '"' + Escape(obj.ToString()) + '"';
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\")
                    .Replace("\"", "\\\"")
                    .Replace("\n", "\\n")
                    .Replace("\r", "\\r")
                    .Replace("\t", "\\t")
                    .Replace("\b", "\\b")
                    .Replace("\f", "\\f");
        }

        // ── Десериализация ─────────────────────────────────────────────────────

        public static Dictionary<string, object> Deserialize(string json)
        {
            if (string.IsNullOrEmpty(json)) return new Dictionary<string, object>();
            json = json.Trim();
            if (json.Length > 5 * 1024 * 1024) throw new FormatException("JSON payload is too large");
            if (json.Length < 2 || json[0] != '{') throw new FormatException("Expected JSON object");
            int pos = 0;
            var result = ParseObject(json, ref pos, 0);
            SkipWs(json, ref pos);
            if (pos != json.Length) throw new FormatException("Trailing JSON data");
            return result;
        }

        public static List<object> DeserializeList(string json)
        {
            if (string.IsNullOrEmpty(json)) return new List<object>();
            json = json.Trim();
            if (json.Length > 5 * 1024 * 1024) throw new FormatException("JSON payload is too large");
            if (json.Length < 2 || json[0] != '[') throw new FormatException("Expected JSON array");
            int pos = 0;
            var result = ParseArray(json, ref pos, 0);
            SkipWs(json, ref pos);
            if (pos != json.Length) throw new FormatException("Trailing JSON data");
            return result;
        }

        // ── Parser internals ───────────────────────────────────────────────────

        private static Dictionary<string, object> ParseObject(string s, ref int pos, int depth)
        {
            if (depth > 64) throw new FormatException("JSON nesting is too deep");
            if (pos >= s.Length || s[pos] != '{') throw new FormatException("Expected '{'");
            var dict = new Dictionary<string, object>();
            pos++; // skip '{'
            SkipWs(s, ref pos);

            if (pos < s.Length && s[pos] == '}')
            {
                pos++;
                return dict;
            }

            while (pos < s.Length)
            {
                SkipWs(s, ref pos);
                if (pos >= s.Length || s[pos] != '"') throw new FormatException("Expected object key");

                string key = ParseString(s, ref pos);
                SkipWs(s, ref pos);
                if (pos >= s.Length || s[pos] != ':') throw new FormatException("Expected ':'");
                pos++;
                SkipWs(s, ref pos);

                object val = ParseValue(s, ref pos, depth + 1);
                dict[key] = val;

                SkipWs(s, ref pos);
                if (pos < s.Length && s[pos] == '}')
                {
                    pos++;
                    return dict;
                }
                if (pos >= s.Length || s[pos] != ',') throw new FormatException("Expected ',' or '}'");
                pos++;
            }

            throw new FormatException("Unterminated JSON object");
        }

        private static List<object> ParseArray(string s, ref int pos, int depth)
        {
            if (depth > 64) throw new FormatException("JSON nesting is too deep");
            if (pos >= s.Length || s[pos] != '[') throw new FormatException("Expected '['");
            var list = new List<object>();
            pos++; // skip '['
            SkipWs(s, ref pos);

            if (pos < s.Length && s[pos] == ']')
            {
                pos++;
                return list;
            }

            while (pos < s.Length)
            {
                list.Add(ParseValue(s, ref pos, depth + 1));
                SkipWs(s, ref pos);
                if (pos < s.Length && s[pos] == ']')
                {
                    pos++;
                    return list;
                }
                if (pos >= s.Length || s[pos] != ',') throw new FormatException("Expected ',' or ']'");
                pos++;
            }

            throw new FormatException("Unterminated JSON array");
        }

        private static object ParseValue(string s, ref int pos, int depth)
        {
            SkipWs(s, ref pos);
            if (pos >= s.Length) return null;

            char c = s[pos];

            if (c == '"') return ParseString(s, ref pos);
            if (c == '{') return ParseObject(s, ref pos, depth);
            if (c == '[') return ParseArray(s, ref pos, depth);

            // null / true / false / number
            int end = pos;
            while (end < s.Length && s[end] != ',' && s[end] != '}' && s[end] != ']') end++;
            string tok = s.Substring(pos, end - pos).Trim();
            pos = end;

            if (tok == "null")  return null;
            if (tok == "true")  return true;
            if (tok == "false") return false;
            if (long.TryParse(tok, out long lng)) return lng;
            if (double.TryParse(tok, System.Globalization.NumberStyles.Any,
                                System.Globalization.CultureInfo.InvariantCulture, out double dbl)) return dbl;
            throw new FormatException($"Invalid JSON token '{tok}'");
        }

        private static string ParseString(string s, ref int pos)
        {
            if (pos >= s.Length || s[pos] != '"') throw new FormatException("Expected string");
            pos++; // skip opening '"'
            var sb = new StringBuilder();
            while (pos < s.Length && s[pos] != '"')
            {
                if (s[pos] == '\\' && pos + 1 < s.Length)
                {
                    pos++;
                    switch (s[pos])
                    {
                        case '"':  sb.Append('"');  break;
                        case '\\': sb.Append('\\'); break;
                        case 'n':  sb.Append('\n'); break;
                        case 'r':  sb.Append('\r'); break;
                        case 't':  sb.Append('\t'); break;
                        case 'b':  sb.Append('\b'); break;
                        case 'f':  sb.Append('\f'); break;
                        case '/':  sb.Append('/');  break;
                        case 'u':
                            if (pos + 4 >= s.Length) throw new FormatException("Invalid unicode escape");
                            int code = 0;
                            for (int i = 1; i <= 4; i++)
                            {
                                int hex = HexValue(s[pos + i]);
                                if (hex < 0) throw new FormatException("Invalid unicode escape");
                                code = (code << 4) | hex;
                            }
                            sb.Append((char)code);
                            pos += 4;
                            break;
                        default: throw new FormatException("Invalid string escape");
                    }
                }
                else
                {
                    if (s[pos] < 0x20) throw new FormatException("Unescaped control character");
                    sb.Append(s[pos]);
                }
                pos++;
            }
            if (pos >= s.Length || s[pos] != '"') throw new FormatException("Unterminated JSON string");
            pos++; // skip closing '"'
            return sb.ToString();
        }

        private static int HexValue(char c)
        {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        }

        private static void SkipWs(string s, ref int pos)
        {
            while (pos < s.Length && char.IsWhiteSpace(s[pos])) pos++;
        }
    }
}
