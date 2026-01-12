package com.syr.dto;

import lombok.Data;

@Data
public class LoginFormDto {
    private String phone;
    private String code;
    private String password;

    // Getters and Setters
    public String getPhone() { return phone; }
    public void setPhone(String phone) { this.phone = phone; }
    public String getCode() { return code; }
    public void setCode(String code) { this.code = code; }
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
}
