from typing import List
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def split_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """
    将长文本按滑动窗口分割成块
    
    参数:
        text: 要分割的文本
        chunk_size: 每个文本块的大小（以单词数计算）
        overlap: 相邻文本块之间的重叠大小
        
    返回:
        分割后的文本块列表
    """
    logger.debug(f"开始分割文本，总长度: {len(text)}, 块大小: {chunk_size}, 重叠: {overlap}")
    
    if not text:
        logger.debug("输入文本为空，返回空列表")
        return []
    
    words = text.split()
    logger.debug(f"文本分词完成，总词数: {len(words)}")
    
    if len(words) <= chunk_size:
        logger.debug("文本长度小于块大小，返回原文本")
        return [text]

    chunks = []
    start = 0
    chunk_num = 0
    
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        # logger.debug(f"生成块 {chunk_num + 1}，长度: {len(chunk)}")
        
        if end >= len(words):
            logger.debug(f"已到达文本末尾，停止分割")
            break
            
        start = end - overlap
        chunk_num += 1
        # logger.debug(f"下一块起始位置: {start}")
        
    logger.debug(f"文本分割完成，共生成 {len(chunks)} 个块")
    return chunks