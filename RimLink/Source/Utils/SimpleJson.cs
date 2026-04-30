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
                    .Replace("\t", "\\t");
        }

        // ── Десериализация ─────────────────────────────────────────────────────

        public static Dictionary<string, object> Deserialize(string json)
        {
            if (string.IsNullOrEmpty(json)) return new Dictionary<string, object>();
            json = json.Trim();
            if (json.Length < 2 || json[0] != '{') return new Dictionary<string, object>();
            int pos = 0;
            return ParseObject(json, ref pos);
        }

        public static List<object> DeserializeList(string json)
        {
            if (string.IsNullOrEmpty(json)) return new List<object>();
            json = json.Trim();
            if (json.Length < 2 || json[0] != '[') return new List<object>();
            int pos = 0;
            return ParseArray(json, ref pos);
        }

        // ── Parser internals ───────────────────────────────────────────────────

        private static Dictionary<string, object> ParseObject(string s, ref int pos)
        {
            var dict = new Dictionary<string, object>();
            pos++; // skip '{'
            SkipWs(s, ref pos);

            while (pos < s.Length && s[pos] != '}')
            {
                SkipWs(s, ref pos);
                if (pos >= s.Length || s[pos] == '}') break;

                string key = ParseString(s, ref pos);
                SkipWs(s, ref pos);
                if (pos < s.Length && s[pos] == ':') pos++;
                SkipWs(s, ref pos);

                object val = ParseValue(s, ref pos);
                dict[key] = val;

                SkipWs(s, ref pos);
                if (pos < s.Length && s[pos] == ',') pos++;
                SkipWs(s, ref pos);
            }

            if (pos < s.Length) pos++; // skip '}'
            return dict;
        }

        private static List<object> ParseArray(string s, ref int pos)
        {
            var list = new List<object>();
            pos++; // skip '['
            SkipWs(s, ref pos);

            while (pos < s.Length && s[pos] != ']')
            {
                list.Add(ParseValue(s, ref pos));
                SkipWs(s, ref pos);
                if (pos < s.Length && s[pos] == ',') pos++;
                SkipWs(s, ref pos);
            }

            if (pos < s.Length) pos++; // skip ']'
            return list;
        }

        private static object ParseValue(string s, ref int pos)
        {
            SkipWs(s, ref pos);
            if (pos >= s.Length) return null;

            char c = s[pos];

            if (c == '"') return ParseString(s, ref pos);
            if (c == '{') return ParseObject(s, ref pos);
            if (c == '[') return ParseArray(s, ref pos);

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
            return tok;
        }

        private static string ParseString(string s, ref int pos)
        {
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
                        default:   sb.Append(s[pos]); break;
                    }
                }
                else sb.Append(s[pos]);
                pos++;
            }
            if (pos < s.Length) pos++; // skip closing '"'
            return sb.ToString();
        }

        private static void SkipWs(string s, ref int pos)
        {
            while (pos < s.Length && char.IsWhiteSpace(s[pos])) pos++;
        }
    }
}
