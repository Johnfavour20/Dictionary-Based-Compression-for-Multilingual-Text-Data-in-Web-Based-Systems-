import struct
from typing import List, Dict, Tuple, Union
import unicodedata
import re

class LZW77Compressor:
    """
    LZW77 (Lempel-Ziv-Welch) compression algorithm implementation
    optimized for multilingual text data.
    """
    
    def __init__(self, max_dict_size: int = 65536, encoding: str = 'utf-8'):
        """
        Initialize the LZW77 compressor
        """
        self.max_dict_size = max_dict_size
        self.encoding = encoding
        self.reset_dictionary()
        
    def reset_dictionary(self):
        """Reset the compression dictionary to initial state"""
        self.dictionary = {}
        self.reverse_dictionary = {}
        
        # Initialize with single characters based on encoding
        for i in range(256):
            try:
                char = bytes([i]).decode(self.encoding, errors='replace')
                self.dictionary[char] = i
                self.reverse_dictionary[i] = char
            except UnicodeDecodeError:
                continue
            
        self.next_code = 256
        
    def compress(self, text: str) -> bytes:
        """
        Compress the input text using the LZW77 algorithm.
        This version correctly handles dictionary resets and characters not in the initial dictionary.
        """
        if not text:
            return b''

        self.reset_dictionary()
        text = unicodedata.normalize('NFC', text)
        
        result = []
        current_string = ""

        for char in text:
            # Check if the new character is in the dictionary after a potential reset
            if char not in self.dictionary:
                if self.next_code < self.max_dict_size:
                    self.dictionary[char] = self.next_code
                    self.reverse_dictionary[self.next_code] = char
                    self.next_code += 1
                else:
                    self.reset_dictionary()
                    # The character should now be added to the newly reset dictionary
                    if char not in self.dictionary:
                        self.dictionary[char] = self.next_code
                        self.reverse_dictionary[self.next_code] = char
                        self.next_code += 1
            
            new_string = current_string + char
            if new_string in self.dictionary:
                current_string = new_string
            else:
                result.append(self.dictionary[current_string])
                
                # Dictionary management logic
                if self.next_code < self.max_dict_size:
                    self.dictionary[new_string] = self.next_code
                    self.reverse_dictionary[self.next_code] = new_string
                    self.next_code += 1
                else:
                    self.reset_dictionary()

                current_string = char

        if current_string:
            result.append(self.dictionary[current_string])
        
        return self._encode_codes(result)
    
    def decompress(self, compressed_data: bytes) -> str:
        """
        Decompress the compressed data back to original text
        """
        if not compressed_data:
            return ""
            
        self.reset_dictionary()
        codes = self._decode_codes(compressed_data)
        
        if not codes:
            return ""
        
        result = []
        old_code = codes[0]
        result.append(self.reverse_dictionary[old_code])
        
        for code in codes[1:]:
            if code in self.reverse_dictionary:
                string = self.reverse_dictionary[code]
            elif code == self.next_code:
                string = self.reverse_dictionary[old_code] + self.reverse_dictionary[old_code][0]
            else:
                raise ValueError(f"Invalid code in compressed data: {code}")
            
            result.append(string)
            if self.next_code < self.max_dict_size:
                new_entry = self.reverse_dictionary[old_code] + string[0]
                self.dictionary[new_entry] = self.next_code
                self.reverse_dictionary[self.next_code] = new_entry
                self.next_code += 1
            else:
                # Reset dictionary when full
                self.reset_dictionary()
                new_entry = self.reverse_dictionary[old_code] + string[0]
                self.dictionary[new_entry] = self.next_code
                self.reverse_dictionary[self.next_code] = new_entry
                self.next_code += 1
            
            old_code = code
        
        return ''.join(result)
    
    def _encode_codes(self, codes: List[int]) -> bytes:
        """
        Encode the list of codes into bytes using variable-length encoding
        """
        packed_codes = b''.join(struct.pack('>H', code) for code in codes)
        header = struct.pack('>I', len(codes))
        header += struct.pack('>I', self.next_code - 256)
        return header + packed_codes
    
    def _decode_codes(self, data: bytes) -> List[int]:
        """
        Decode bytes back into list of codes
        """
        if len(data) < 8:
            return []
        
        num_codes = struct.unpack('>I', data[0:4])[0]
        dict_size_used = struct.unpack('>I', data[4:8])[0]
        codes_data = data[8:]
        codes = []
        
        for i in range(num_codes):
            if i * 2 + 2 <= len(codes_data):
                code = struct.unpack('>H', codes_data[i*2:(i*2)+2])[0]
                codes.append(code)
            else:
                break
        
        return codes
    
    def get_compression_stats(self, original_text: str, compressed_data: bytes) -> Dict[str, Union[int, float]]:
        """
        Calculate compression statistics
        """
        original_size = len(original_text.encode(self.encoding))
        compressed_size = len(compressed_data)
        
        if original_size == 0:
            return {
                'original_size': 0,
                'compressed_size': compressed_size,
                'compression_ratio': 0,
                'space_saved': 0
            }
        
        compression_ratio = (1 - (compressed_size / original_size)) * 100
        space_saved = original_size - compressed_size
        
        return {
            'original_size': original_size,
            'compressed_size': compressed_size,
            'compression_ratio': round(compression_ratio, 2),
            'space_saved': space_saved
        }


class MultilingualDictionary:
    """
    Enhanced dictionary for multilingual text compression
    """
    
    def __init__(self):
        """Initialize with common multilingual patterns"""
        self.common_words = {
            'the', 'and', 'is', 'in', 'to', 'of', 'a', 'that', 'it', 'with', 'for', 'as', 'was', 'on', 'are',
            'el', 'la', 'de', 'que', 'y', 'en', 'un', 'es', 'se', 'no', 'te', 'lo', 'le', 'da', 'su',
            'le', 'de', 'et', 'à', 'un', 'il', 'être', 'et', 'en', 'avoir', 'que', 'pour', 'dans', 'ce', 'son',
            'der', 'die', 'und', 'in', 'den', 'von', 'zu', 'das', 'mit', 'sich', 'des', 'auf', 'für', 'ist', 'im',
            'o', 'a', 'do', 'da', 'em', 'um', 'para', 'é', 'com', 'não', 'uma', 'os', 'no', 'se', 'na',
            'il', 'di', 'che', 'è', 'e', 'la', 'per', 'una', 'in', 'del', 'un', 'da', 'essere', 'con', 'su',
            'и', 'в', 'не', 'на', 'я', 'быть', 'он', 'с', 'а', 'как', 'по', 'это', 'она', 'к', 'но',
            '的', '一', '是', '在', '不', '了', '有', '和', '人', '这', '中', '大', '为', '上', '个',
            'في', 'من', 'إلى', 'على', 'أن', 'هذا', 'هذه', 'التي', 'الذي', 'كان', 'كل', 'عن', 'مع', 'أو', 'كما'
        }
        self.common_patterns = {
            '. ', ', ', '; ', ': ', '! ', '? ', '\n', '\r\n', '\t', '  ',
            '()', '[]', '{}', '""', "''", '--', '...', ' - ', ' / '
        }


class HybridLZW77Compressor(LZW77Compressor):
    """
    Enhanced LZW77 compressor with static multilingual dictionary
    """
    
    def __init__(self, max_dict_size: int = 65536, encoding: str = 'utf-8'):
        """Initialize with multilingual dictionary support"""
        self.multilingual_dict = MultilingualDictionary()
        super().__init__(max_dict_size, encoding)
    
    def reset_dictionary(self):
        """Reset dictionary including multilingual patterns"""
        super().reset_dictionary()
        all_patterns = list(self.multilingual_dict.common_words) + list(self.multilingual_dict.common_patterns)
        
        for pattern in all_patterns:
            if pattern not in self.dictionary and self.next_code < self.max_dict_size:
                self.dictionary[pattern] = self.next_code
                self.reverse_dictionary[self.next_code] = pattern
                self.next_code += 1
    
    def preprocess_text(self, text: str) -> str:
        """
        Preprocess text for better compression
        """
        text = unicodedata.normalize('NFC', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n+', '\n', text)
        return text.strip()
    
    def compress(self, text: str) -> bytes:
        """Enhanced compression with preprocessing"""
        try:
            preprocessed_text = self.preprocess_text(text)
            return super().compress(preprocessed_text)
        except Exception as e:
            raise ValueError(f"Compression failed: {str(e)}")
    
    def decompress(self, compressed_data: bytes) -> str:
        """Enhanced decompression"""
        try:
            return super().decompress(compressed_data)
        except Exception as e:
            raise ValueError(f"Decompression failed: {str(e)}")